from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from importlib import import_module

from . import db
from .registry import registry

protocol = import_module('07_servises.common.protocol')
log = logging.getLogger(__name__)


class UpdateOrchestrator:
    """One-module-at-a-time staged updater.

    The firewall hook is dry-run by default. Site-specific Zyxel/nftables integration
    can replace the hook without changing updater sequencing.
    """

    def __init__(self, hook: str = '07_servises/firewall_update_hook.sh', update_port: int = 6503):
        self.hook = Path(hook)
        self.update_port = update_port
        self._lock = asyncio.Lock()

    async def _firewall(self, action: str, ip: str) -> None:
        proc = await asyncio.create_subprocess_exec(str(self.hook), action, ip)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f'firewall hook failed ({action} {ip}) rc={rc}')

    async def _request_update(self, ip: str, command: list[str] | None = None) -> dict:
        reader, writer = await asyncio.open_connection(ip, self.update_port)
        try:
            await protocol.write_frame(writer, {
                'type': 'update_run',
                'payload': {'command': command or ['sudo', 'apt-get', 'update']},
            })
            return (await protocol.read_frame(reader)).get('payload', {})
        finally:
            writer.close()
            await writer.wait_closed()

    async def update_module(self, hostname: str, command: list[str] | None = None, return_timeout_s: int = 180) -> dict:
        async with self._lock:
            async with db.acquire() as conn:
                row = await conn.fetchrow('SELECT module_uuid, ip_address FROM modules WHERE hostname=$1', hostname)
            if not row:
                raise KeyError(hostname)
            module_uuid, ip = str(row['module_uuid']), str(row['ip_address'])
            await self._firewall('open', ip)
            try:
                result = await self._request_update(ip, command)
                if not result.get('ok') and not result.get('dry_run'):
                    raise RuntimeError(f'update failed: {result}')
                deadline = asyncio.get_running_loop().time() + return_timeout_s
                while asyncio.get_running_loop().time() < deadline:
                    conn = registry.connections.get(module_uuid)
                    if conn and conn.last_heartbeat:
                        return {'ok': True, 'module': hostname, 'update': result, 'verified': True}
                    await asyncio.sleep(2)
                raise TimeoutError(f'{hostname} did not return heartbeat after update')
            finally:
                await self._firewall('close', ip)

updater = UpdateOrchestrator()
