from __future__ import annotations
import asyncio
import json
import logging
import ssl
import time
import uuid
from pathlib import Path
from typing import Any
from importlib import import_module
from . import db
from .settings import settings

protocol = import_module('07_servises.common.protocol')
log = logging.getLogger(__name__)

RANGES = {
    'RCM': range(20, 30),
    'LCM': range(30, 40),
    'SIM': range(40, 50),
    'PNL': range(50, 90),
}

class ModuleConnection:
    def __init__(self, reader, writer):
        self.reader = reader; self.writer = writer
        self.module_uuid: str | None = None
        self.hostname: str | None = None
        self.last_heartbeat = 0.0
        self.pending: dict[str, asyncio.Future] = {}

    async def send(self, typ: str, payload: dict[str, Any], request_id: str | None = None):
        await protocol.write_frame(self.writer, {'type': typ, 'payload': payload, **({'request_id': request_id} if request_id else {})})

    async def command(self, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        rid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.send('command', payload, rid)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

class ModuleRegistry:
    def __init__(self):
        self.connections: dict[str, ModuleConnection] = {}
        self.server: asyncio.AbstractServer | None = None

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client,
            settings.module_host,
            settings.module_port,
            ssl=self._ssl_context(),
        )
        log.info('module server listening on %s:%s', settings.module_host, settings.module_port)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not settings.tls_enabled:
            return None
        if not settings.tls_cert or not settings.tls_key:
            raise RuntimeError('HCM_TLS_ENABLED requires HCM_TLS_CERT and HCM_TLS_KEY')
        if settings.tls_require_client_cert and not settings.tls_ca:
            raise RuntimeError('HCM_TLS_REQUIRE_CLIENT_CERT requires HCM_TLS_CA')
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(settings.tls_cert, settings.tls_key)
        if settings.tls_ca:
            ctx.load_verify_locations(settings.tls_ca)
        if settings.tls_require_client_cert:
            ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    async def stop(self):
        if self.server:
            self.server.close(); await self.server.wait_closed()

    async def _assign(self, ident: dict[str, Any]) -> dict[str, Any]:
        typ = str(ident.get('module_type','')).upper()
        if typ not in RANGES:
            raise ValueError(f'unsupported module type {typ}')
        module_uuid = ident['module_uuid']
        async with db.acquire() as conn:
            row = await conn.fetchrow('SELECT hostname, ip_address FROM modules WHERE module_uuid=$1', module_uuid)
            if row:
                return {'hostname': row['hostname'], 'ip_address': str(row['ip_address']), 'reboot_required': False}
            if not settings.commissioning_enabled:
                raise PermissionError(f'commissioning disabled for unknown {typ} module {module_uuid}')
            used = {int(str(r['ip_address']).split('.')[-1]) for r in await conn.fetch('SELECT ip_address FROM modules WHERE module_type=$1', typ)}
            octet = next((n for n in RANGES[typ] if n not in used), None)
            if octet is None:
                raise RuntimeError(f'no addresses left in {typ} pool')
            seq = octet - RANGES[typ].start + 1
            hostname = f'{typ}{seq:02d}'
            ip = f'192.168.60.{octet}'
            await conn.execute('''
                INSERT INTO modules(module_uuid,module_type,hostname,ip_address,software_version,last_seen,online)
                VALUES($1,$2,$3,$4,$5,now(),true)
            ''', module_uuid, typ, hostname, ip, ident.get('software_version'))
            return {'hostname': hostname, 'ip_address': ip, 'reboot_required': True}

    async def _base_config(self, module_type: str) -> dict[str, Any]:
        path = Path(settings.config_root) / {
            'RCM':'04_RCM','LCM':'03_LCM','SIM':'02_SIM','PNL':'05_PNL'
        }[module_type] / f'{module_type.lower()}.yaml'
        if not path.exists():
            return {'version': 1}
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
        return {'version': int(data.get('config_version',1)), 'config': data}

    async def handle_client(self, reader, writer):
        conn = ModuleConnection(reader, writer)
        peer = writer.get_extra_info('peername')
        try:
            first = await protocol.read_frame(reader)
            if first.get('type') != 'identify':
                raise protocol.ProtocolError('first message must be identify')
            if settings.tls_enabled and settings.tls_require_client_cert and not writer.get_extra_info('peercert'):
                raise protocol.ProtocolError('client certificate required')
            ident = first.get('payload', {})
            conn.module_uuid = ident['module_uuid']
            assignment = await self._assign(ident)
            conn.hostname = assignment['hostname']
            self.connections[conn.module_uuid] = conn
            if ident.get('hostname') != assignment['hostname'] or ident.get('assigned_ip') != assignment['ip_address']:
                await conn.send('assignment', assignment)
            else:
                await conn.send('config', await self._base_config(ident['module_type']))

            async with db.acquire() as dbc:
                await dbc.execute('UPDATE modules SET online=true,last_seen=now(),software_version=$2 WHERE module_uuid=$1', conn.module_uuid, ident.get('software_version'))

            while True:
                msg = await protocol.read_frame(reader)
                typ = msg.get('type')
                payload = msg.get('payload', {})
                if typ == 'heartbeat':
                    conn.last_heartbeat = time.time()
                    async with db.acquire() as dbc:
                        await dbc.execute('''UPDATE modules SET online=true,last_seen=now(),last_state=$2::jsonb WHERE module_uuid=$1''', conn.module_uuid, json.dumps(payload))
                    await conn.send('heartbeat_ack', {'ts': time.time()})
                elif typ == 'state':
                    async with db.acquire() as dbc:
                        await dbc.execute('''UPDATE modules SET last_state=$2::jsonb,last_seen=now() WHERE module_uuid=$1''', conn.module_uuid, json.dumps(payload))
                elif typ == 'fault':
                    async with db.acquire() as dbc:
                        await dbc.execute('''INSERT INTO faults(module_uuid,code,severity,details) VALUES($1,$2,$3,$4::jsonb)''', conn.module_uuid, payload.get('code','unknown'), payload.get('severity','warning'), json.dumps(payload))
                elif typ == 'command_ack':
                    rid = msg.get('request_id')
                    fut = conn.pending.get(rid)
                    if fut and not fut.done(): fut.set_result(payload)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            log.exception('module connection error from %s', peer)
        finally:
            if conn.module_uuid:
                self.connections.pop(conn.module_uuid, None)
                try:
                    async with db.acquire() as dbc:
                        await dbc.execute('UPDATE modules SET online=false WHERE module_uuid=$1', conn.module_uuid)
                except Exception:
                    log.exception('failed marking module offline')
            writer.close()
            try: await writer.wait_closed()
            except Exception: pass

    async def command_by_hostname(self, hostname: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        async with db.acquire() as conn:
            row = await conn.fetchrow('SELECT module_uuid FROM modules WHERE hostname=$1', hostname)
        if not row: raise KeyError(hostname)
        mc = self.connections.get(str(row['module_uuid']))
        if not mc: raise ConnectionError(f'{hostname} offline')
        return await mc.command(payload, timeout=timeout)

registry = ModuleRegistry()
