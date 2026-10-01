from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

from .protocol import read_frame, write_frame

log = logging.getLogger(__name__)

class ModuleAgent:
    def __init__(self, module_type: str, config: dict[str, Any]):
        self.module_type = module_type.upper()
        self.config = config
        self.hcm_host = config.get('hcm_host', '192.168.60.1')
        self.hcm_port = int(config.get('hcm_port', 6501))
        self.heartbeat_s = float(config.get('heartbeat_seconds', 5))
        self.identity_path = Path(config.get('identity_path', './runtime/identity.json'))
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = self._load_identity()
        self.state: dict[str, Any] = {}
        self.faults: dict[str, Any] = {}
        self.running = True

    def _machine_id(self) -> str:
        for p in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                val = Path(p).read_text().strip()
                if val:
                    return val
            except OSError:
                pass
        return str(uuid.getnode())

    def _load_identity(self) -> dict[str, Any]:
        if self.identity_path.exists():
            return json.loads(self.identity_path.read_text())
        return {
            'module_type': self.module_type,
            'module_uuid': str(uuid.uuid5(uuid.NAMESPACE_DNS, f'homecontrol:{self.module_type}:{self._machine_id()}')),
            'hostname': self.module_type,
            'assigned_ip': None,
            'commissioned': False,
            'config_version': 0,
        }

    def save_identity(self) -> None:
        self.identity_path.write_text(json.dumps(self.identity, indent=2))

    async def collect_state(self) -> dict[str, Any]:
        return self.state

    async def apply_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {'ok': False, 'error': 'command_not_implemented'}

    async def apply_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.identity['config_version'] = int(payload.get('version', self.identity.get('config_version', 0)))
        self.save_identity()
        return {'ok': True, 'config_version': self.identity['config_version']}

    async def apply_assignment(self, payload: dict[str, Any]) -> dict[str, Any]:
        # First pass: persist the desired identity. OS hostname/network changes are intentionally
        # delegated to an installer/service hook so dev machines are never reconfigured by accident.
        self.identity.update({
            'hostname': payload['hostname'],
            'assigned_ip': payload['ip_address'],
            'commissioned': True,
        })
        self.save_identity()
        return {'ok': True, 'reboot_required': bool(payload.get('reboot_required', True))}

    def _ssl_context(self) -> ssl.SSLContext | None:
        tls = self.config.get('tls', {})
        if not tls.get('enabled', False):
            return None
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=tls.get('ca_file'))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = bool(tls.get('check_hostname', True))
        cert = tls.get('cert_file')
        key = tls.get('key_file')
        if cert and key:
            ctx.load_cert_chain(cert, key)
        return ctx

    async def _session(self) -> None:
        tls = self.config.get('tls', {})
        server_hostname = tls.get('server_hostname', self.hcm_host) if tls.get('enabled', False) else None
        reader, writer = await asyncio.open_connection(
            self.hcm_host,
            self.hcm_port,
            ssl=self._ssl_context(),
            server_hostname=server_hostname,
        )
        await write_frame(writer, {
            'type': 'identify',
            'payload': {
                **self.identity,
                'reported_hostname': socket.gethostname(),
                'software_version': self.config.get('software_version', '0.1.0'),
                'capabilities': self.config.get('capabilities', []),
            }
        })
        reply = await read_frame(reader)
        if reply.get('type') == 'assignment':
            ack = await self.apply_assignment(reply.get('payload', {}))
            await write_frame(writer, {'type': 'command_ack', 'payload': ack, 'request_id': reply.get('request_id')})
            # Commissioning requires the module to return using its permanent identity.
            # The installer may replace this reconnect with a real OS hostname/IP update + reboot.
            writer.close()
            await writer.wait_closed()
            return
        if reply.get('type') == 'config':
            ack = await self.apply_config(reply.get('payload', {}))
            await write_frame(writer, {'type': 'command_ack', 'payload': ack, 'request_id': reply.get('request_id')})

        async def heartbeat_loop():
            while self.running:
                await asyncio.sleep(self.heartbeat_s)
                state = await self.collect_state()
                await write_frame(writer, {
                    'type': 'heartbeat',
                    'payload': {
                        'module_uuid': self.identity['module_uuid'],
                        'hostname': self.identity['hostname'],
                        'ts': time.time(),
                        'state': state,
                        'faults': self.faults,
                    }
                })

        hb = asyncio.create_task(heartbeat_loop())
        try:
            while self.running:
                msg = await read_frame(reader)
                typ = msg.get('type')
                if typ == 'heartbeat_ack':
                    continue
                if typ == 'command':
                    result = await self.apply_command(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
                elif typ == 'config':
                    result = await self.apply_config(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
        finally:
            hb.cancel()
            writer.close()
            await writer.wait_closed()

    async def run(self) -> None:
        delay = 1
        while self.running:
            try:
                await self._session()
                delay = 1
            except (OSError, asyncio.IncompleteReadError, ConnectionError) as exc:
                log.warning('%s disconnected: %s', self.module_type, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
