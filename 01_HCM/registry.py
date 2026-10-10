from __future__ import annotations
import asyncio
import ipaddress
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
from homecontrol_identity import InvalidDeviceId, maybe_normalize_device_id

protocol = import_module('07_servises.common.protocol')
log = logging.getLogger(__name__)

MODULE_TYPES = ('RCM', 'LCM', 'SIM', 'PNL')

class ControlNetworkPlan:
    def __init__(self, profile_name: str, data: dict[str, Any]):
        self.profile_name = profile_name
        self.vlan = data.get('vlan')
        self.subnet = data.get('subnet')
        self.pools = data.get('pools') or {}
        self.require_explicit_subnet = bool(data.get('require_explicit_subnet', False))
        self.assignment_enabled = data.get('assignment_enabled', True)
        if self.assignment_enabled is None:
            self.assignment_enabled = True
        if not self.subnet:
            if self.require_explicit_subnet:
                raise RuntimeError(f'control network profile {profile_name} requires an approved subnet')
            raise RuntimeError(f'control network profile {profile_name} has no subnet')
        self.network = ipaddress.ip_network(str(self.subnet), strict=False)
        if int(self.vlan) == 60:
            raise RuntimeError('VLAN 60 is reserved for heartbeat/supervisory traffic and cannot be used for control assignment')
        if not self.assignment_enabled:
            raise RuntimeError(f'control network profile {profile_name} is not enabled for assignment')

    def addresses_for(self, module_type: str) -> list[str]:
        pool = self.pools.get(module_type)
        if not pool:
            raise RuntimeError(f'control network profile {self.profile_name} has no {module_type} pool')
        start = ipaddress.ip_address(str(pool['start']))
        end = ipaddress.ip_address(str(pool['end']))
        if start.version != 4 or end.version != 4 or start > end:
            raise RuntimeError(f'invalid {module_type} control pool in {self.profile_name}')
        if start not in self.network or end not in self.network:
            raise RuntimeError(f'{module_type} control pool is outside {self.profile_name} subnet')
        if self.network.network_address in (start, end) or self.network.broadcast_address in (start, end):
            raise RuntimeError(f'{module_type} control pool uses reserved subnet address')
        return [str(ipaddress.ip_address(value)) for value in range(int(start), int(end) + 1)]

def load_control_network_plan() -> ControlNetworkPlan:
    path = Path(settings.config_root) / '01_HCM' / 'hcm.yaml'
    if not path.exists():
        raise RuntimeError(f'HCM control network configuration missing: {path}')
    import yaml
    data = yaml.safe_load(path.read_text()) or {}
    control = (data.get('network') or {}).get('control') or {}
    profile_name = control.get('active_profile')
    profiles = control.get('profiles') or {}
    if not profile_name:
        raise RuntimeError('network.control.active_profile is required')
    profile = profiles.get(profile_name)
    if not profile:
        raise RuntimeError(f'control network profile {profile_name} is not defined')
    return ControlNetworkPlan(profile_name, profile)

class ModuleConnection:
    def __init__(self, reader, writer):
        self.reader = reader; self.writer = writer
        self.device_id: str | None = None
        self.module_uuid: str | None = None
        self.connection_key: str | None = None
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
        if typ not in MODULE_TYPES:
            raise ValueError(f'unsupported module type {typ}')
        device_id = self._device_id_from_ident(ident)
        module_uuid = ident.get('module_uuid')
        if not device_id and not module_uuid:
            raise ValueError('identify requires device_id or legacy module_uuid')
        identity_label = device_id or module_uuid
        async with db.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT hostname, ip_address
                FROM modules
                WHERE ($1::text IS NOT NULL AND device_id=$1)
                   OR ($2::text IS NOT NULL AND module_uuid::text=$2)
            ''', device_id, module_uuid)
            if row:
                return {'hostname': row['hostname'], 'ip_address': str(row['ip_address']), 'reboot_required': False}
            if not settings.commissioning_enabled:
                raise PermissionError(f'commissioning disabled for unknown {typ} module {identity_label}')
            plan = load_control_network_plan()
            addresses = plan.addresses_for(typ)
            used = {str(r['ip_address']) for r in await conn.fetch('SELECT ip_address FROM modules WHERE module_type=$1', typ)}
            ip = next((candidate for candidate in addresses if candidate not in used), None)
            if ip is None:
                raise RuntimeError(f'no addresses left in {typ} pool')
            seq = addresses.index(ip) + 1
            hostname = f'{typ}{seq:02d}'
            await conn.execute('''
                INSERT INTO modules(
                    device_id,module_uuid,identity_interface,module_type,hostname,
                    ip_address,software_version,last_seen,online,control_session_online
                )
                VALUES($1,$2,$3,$4,$5,$6,$7,now(),true,true)
            ''',
                device_id,
                module_uuid,
                ident.get('identity_interface') or (ident.get('identity') or {}).get('interface'),
                typ,
                hostname,
                ip,
                ident.get('software_version'),
            )
            return {'hostname': hostname, 'ip_address': ip, 'reboot_required': True}

    def _device_id_from_ident(self, ident: dict[str, Any]) -> str | None:
        raw = ident.get('device_id')
        if raw:
            return maybe_normalize_device_id(raw)
        legacy = ident.get('module_uuid')
        try:
            return maybe_normalize_device_id(legacy)
        except InvalidDeviceId:
            return None

    async def _base_config(self, module_type: str) -> dict[str, Any]:
        path = Path(settings.config_root) / {
            'RCM':'04_RCM','LCM':'03_LCM','SIM':'02_SIM','PNL':'05_PNL'
        }[module_type] / f'{module_type.lower()}.yaml'
        if not path.exists():
            return {'version': 1}
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
        return {'version': int(data.get('config_version',1)), 'config': data}

    def _capability_rows(self, ident: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for item in ident.get('capabilities') or []:
            if isinstance(item, str):
                name = item.strip()
                details: dict[str, Any] = {}
            elif isinstance(item, dict):
                raw_name = item.get('capability') or item.get('name') or item.get('type')
                name = str(raw_name or '').strip()
                details = {k: v for k, v in item.items() if k not in {'capability', 'name'}}
            else:
                continue
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append((name, details))
        return rows

    async def _store_capabilities(self, dbc, device_id: str | None, module_uuid: str | None, ident: dict[str, Any]) -> None:
        capabilities = self._capability_rows(ident)
        if not capabilities:
            return
        row = await dbc.fetchrow('''
            SELECT id
            FROM modules
            WHERE ($1::text IS NOT NULL AND device_id=$1)
               OR ($2::text IS NOT NULL AND module_uuid::text=$2)
        ''', device_id, module_uuid)
        if not row:
            return
        module_id = int(row['id'])
        await dbc.execute(
            'DELETE FROM module_capabilities WHERE module_id=$1 AND NOT (capability=ANY($2::text[]))',
            module_id,
            [name for name, _details in capabilities],
        )
        for name, details in capabilities:
            await dbc.execute('''
                INSERT INTO module_capabilities(module_id, capability, details, updated_at)
                VALUES($1,$2,$3::jsonb,now())
                ON CONFLICT(module_id, capability)
                DO UPDATE SET details=EXCLUDED.details, updated_at=now()
            ''', module_id, name, json.dumps(details))

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
            conn.device_id = self._device_id_from_ident(ident)
            conn.module_uuid = ident.get('module_uuid')
            conn.connection_key = conn.device_id or conn.module_uuid
            assignment = await self._assign(ident)
            conn.hostname = assignment['hostname']
            self.connections[conn.connection_key] = conn
            if ident.get('hostname') != assignment['hostname'] or ident.get('assigned_ip') != assignment['ip_address']:
                await conn.send('assignment', assignment)
            else:
                await conn.send('config', await self._base_config(ident['module_type']))

            async with db.acquire() as dbc:
                await dbc.execute('''
                    UPDATE modules
                    SET online=true,
                        control_session_online=true,
                        last_seen=now(),
                        software_version=$3,
                        identity_interface=COALESCE($4, identity_interface)
                    WHERE ($1::text IS NOT NULL AND device_id=$1)
                       OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                ''',
                    conn.device_id,
                    conn.module_uuid,
                    ident.get('software_version'),
                    ident.get('identity_interface') or (ident.get('identity') or {}).get('interface'),
                )
                await self._store_capabilities(dbc, conn.device_id, conn.module_uuid, ident)

            while True:
                msg = await protocol.read_frame(reader)
                typ = msg.get('type')
                payload = msg.get('payload', {})
                if typ == 'heartbeat':
                    conn.last_heartbeat = time.time()
                    async with db.acquire() as dbc:
                        await dbc.execute('''
                            UPDATE modules
                            SET online=true,
                                control_session_online=true,
                                last_seen=now(),
                                last_state=$3::jsonb
                            WHERE ($1::text IS NOT NULL AND device_id=$1)
                               OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                        ''', conn.device_id, conn.module_uuid, json.dumps(payload))
                    await conn.send('heartbeat_ack', {'ts': time.time()})
                elif typ == 'state':
                    async with db.acquire() as dbc:
                        await dbc.execute('''
                            UPDATE modules
                            SET last_state=$3::jsonb,
                                last_seen=now()
                            WHERE ($1::text IS NOT NULL AND device_id=$1)
                               OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                        ''', conn.device_id, conn.module_uuid, json.dumps(payload))
                elif typ == 'fault':
                    async with db.acquire() as dbc:
                        await dbc.execute('''INSERT INTO faults(device_id,module_uuid,code,severity,details) VALUES($1,$2,$3,$4,$5::jsonb)''', conn.device_id, conn.module_uuid, payload.get('code','unknown'), payload.get('severity','warning'), json.dumps(payload))
                elif typ == 'command_ack':
                    rid = msg.get('request_id')
                    fut = conn.pending.get(rid)
                    if fut and not fut.done(): fut.set_result(payload)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            log.exception('module connection error from %s', peer)
        finally:
            if conn.connection_key:
                self.connections.pop(conn.connection_key, None)
                try:
                    async with db.acquire() as dbc:
                        await dbc.execute('''
                            UPDATE modules
                            SET online=false,
                                control_session_online=false
                            WHERE ($1::text IS NOT NULL AND device_id=$1)
                               OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                        ''', conn.device_id, conn.module_uuid)
                except Exception:
                    log.exception('failed marking module offline')
            writer.close()
            try: await writer.wait_closed()
            except Exception: pass

    async def command_by_hostname(self, hostname: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        async with db.acquire() as conn:
            row = await conn.fetchrow('SELECT device_id, module_uuid::text AS module_uuid FROM modules WHERE hostname=$1', hostname)
        if not row: raise KeyError(hostname)
        key = row['device_id'] or str(row['module_uuid'])
        mc = self.connections.get(key)
        if not mc: raise ConnectionError(f'{hostname} offline')
        return await mc.command(payload, timeout=timeout)

registry = ModuleRegistry()
