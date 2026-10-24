from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path
from importlib import import_module
from typing import Any

from . import db
from .registry import registry
from .settings import settings

protocol = import_module('08_servises.common.protocol')
global_config = import_module('08_servises.common.global_config')
log = logging.getLogger(__name__)


class UpdateOrchestrator:
    """One-module-at-a-time staged updater.

    The firewall hook is dry-run by default. Site-specific Zyxel/nftables integration
    can replace the hook without changing updater sequencing.
    """

    def __init__(self, hook: str = '08_servises/firewall_update_hook.sh', update_port: int | None = None, globals_=None):
        self.globals = globals_ or global_config.load_global_config('HCM')
        self.hook = Path(hook)
        self.update_port = int(update_port or self.globals.API_Update_Port)
        self.module_return_timeout_s = float(self.globals.Updater_Module_Return_Timeout) / 1000.0
        self.module_poll_interval_s = float(self.globals.Updater_Module_Poll_Interval) / 1000.0
        self._lock = asyncio.Lock()

    async def _firewall(self, action: str, ip: str) -> None:
        proc = await asyncio.create_subprocess_exec(str(self.hook), action, ip)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f'firewall hook failed ({action} {ip}) rc={rc}')

    async def _request_update(self, ip: str, artifact: dict[str, Any]) -> dict:
        reader, writer = await asyncio.open_connection(ip, self.update_port)
        try:
            secret_path = getattr(self.globals, 'Update_Request_Secret_File', None) or settings.update_request_secret_file
            if not secret_path or not Path(secret_path).is_file():
                raise RuntimeError('update request authentication secret is unavailable')
            secret = Path(secret_path).read_bytes().strip()
            operation_id = str(uuid.uuid4())
            timestamp = float(time.time())
            request_id = str(uuid.uuid4())
            payload = {'artifact': artifact}
            canonical = json.dumps({'type': 'update_run', 'payload': payload, 'request_id': request_id, 'operation_id': operation_id, 'artifact_id': str(artifact.get('artifact_id', '')), 'timestamp': timestamp}, sort_keys=True, separators=(',', ':')).encode()
            await protocol.write_frame(writer, {
                'type': 'update_run',
                'payload': payload,
                'request_id': request_id,
                'auth': {'operation_id': operation_id, 'artifact_id': str(artifact.get('artifact_id', '')), 'timestamp': timestamp, 'mac': hmac.new(secret, canonical, hashlib.sha256).hexdigest()},
            })
            return (await protocol.read_frame(reader)).get('payload', {})
        finally:
            writer.close()
            await writer.wait_closed()

    async def update_module(self, hostname: str, artifact: dict[str, Any], return_timeout_s: int | None = None) -> dict:
        async with self._lock:
            async with db.acquire() as conn:
                row = await conn.fetchrow('SELECT device_id, module_uuid::text AS module_uuid, ip_address FROM modules WHERE hostname=$1', hostname)
            if not row:
                raise KeyError(hostname)
            module_key, ip = row['device_id'] or str(row['module_uuid']), str(row['ip_address'])
            async with db.acquire() as conn:
                before = await conn.fetchrow(
                    'SELECT last_seen, software_version FROM modules WHERE hostname=$1', hostname
                )
            before_seen = before['last_seen'] if before else None
            await self._firewall('open', ip)
            try:
                result = await self._request_update(ip, artifact)
                if not result.get('ok') and not result.get('dry_run'):
                    raise RuntimeError(f'update failed: {result}')
                deadline = asyncio.get_running_loop().time() + (return_timeout_s if return_timeout_s is not None else self.module_return_timeout_s)
                while asyncio.get_running_loop().time() < deadline:
                    connection = registry.connections.get(module_key)
                    async with db.acquire() as conn:
                        current = await conn.fetchrow(
                            'SELECT last_seen, software_version FROM modules WHERE hostname=$1', hostname
                        )
                    newer_heartbeat = bool(current and current['last_seen'] and (before_seen is None or current['last_seen'] > before_seen))
                    if connection and connection.last_heartbeat and newer_heartbeat:
                        expected = str(artifact.get('version') or artifact.get('software_version') or '')
                        version_ok = not expected or str(current['software_version'] or '') == expected
                        return {
                            'ok': version_ok,
                            'module': hostname,
                            'update': result,
                            'verified': version_ok,
                            'reason': None if version_ok else 'version_mismatch',
                            'verification': {'new_heartbeat': True, 'reported_version': current['software_version'], 'version_match': version_ok},
                        }
                    await asyncio.sleep(self.module_poll_interval_s)
                raise TimeoutError(f'{hostname} did not return heartbeat after update')
            finally:
                await self._firewall('close', ip)


updater = UpdateOrchestrator()
