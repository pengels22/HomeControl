from __future__ import annotations
import asyncio
import ipaddress
import json
import logging
import re
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from importlib import import_module
from . import db
from . import storage
from . import role_switching
from .settings import settings
from homecontrol_identity import InvalidDeviceId, maybe_normalize_device_id

protocol = import_module('07_servises.common.protocol')
module_infra = import_module('07_servises.common.module_infra')
log = logging.getLogger(__name__)

MODULE_TYPES = ('RCM', 'LCM', 'SIM', 'PNL')
LAB1_SIMULATED_MODULE_TYPES = {'RCM', 'SIM', 'LCM'}
DEVICE_URI_PREFIX = 'urn:homecontrol:device:'


@asynccontextmanager
async def _transaction(conn):
    tx_factory = getattr(conn, "transaction", None)
    if tx_factory is None:
        yield
        return
    async with tx_factory():
        yield

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
        self.module_type: str | None = None
        self.connection_key: str | None = None
        self.hostname: str | None = None
        self.last_heartbeat = 0.0
        self.pending: dict[str, asyncio.Future] = {}

    async def send(self, typ: str, payload: dict[str, Any], request_id: str | None = None):
        await protocol.write_frame(self.writer, {'type': typ, 'payload': payload, **({'request_id': request_id} if request_id else {})})

    async def command(self, payload: dict[str, Any], timeout: float = 10.0, request_id: str | None = None) -> dict[str, Any]:
        rid = request_id or str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.send('command', payload, rid)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

    async def config(self, payload: dict[str, Any], timeout: float = 10.0, request_id: str | None = None) -> dict[str, Any]:
        rid = request_id or str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.send('config', payload, rid)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

class ModuleRegistry:
    def __init__(self):
        self.connections: dict[str, ModuleConnection] = {}
        self._connections_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_transition_hook = None
        self.server: asyncio.AbstractServer | None = None

    async def start(self):
        self._validate_module_listener_security()
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

    def _certificate_identity_enforced(self) -> bool:
        return bool(
            settings.tls_enabled
            and settings.tls_require_client_cert
            and settings.module_cert_identity_required
        )

    def _validate_module_listener_security(self) -> None:
        if settings.allow_insecure_module_listener:
            return
        if not settings.tls_enabled:
            raise RuntimeError('HCM module listener requires TLS unless HCM_ALLOW_INSECURE_MODULE_LISTENER is enabled')
        if not settings.tls_require_client_cert:
            raise RuntimeError('HCM module listener requires client certificates')
        if not settings.module_cert_identity_required:
            raise RuntimeError('HCM module listener requires client certificate device identity enforcement')

    async def stop(self):
        if self.server:
            self.server.close(); await self.server.wait_closed()

    async def _register_connection(self, key: str, conn: ModuleConnection) -> None:
        async with self._connections_lock:
            self.connections[key] = conn

    async def _unregister_connection(self, conn: ModuleConnection) -> bool:
        if not conn.connection_key:
            return False
        async with self._connections_lock:
            if self.connections.get(conn.connection_key) is conn:
                self.connections.pop(conn.connection_key, None)
                return True
        return False

    async def _session_lock(self, key: str) -> asyncio.Lock:
        async with self._connections_lock:
            lock = self._session_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[key] = lock
            return lock

    async def _transition_hook(self, event: str, key: str, conn: ModuleConnection) -> None:
        hook = self._session_transition_hook
        if hook is not None:
            await hook(event, key, conn)

    async def _activate_connection(self, conn: ModuleConnection, ident: dict[str, Any]) -> None:
        if not conn.connection_key:
            raise ValueError('connection has no identity key')
        lock = await self._session_lock(conn.connection_key)
        await self._transition_hook('activate_waiting', conn.connection_key, conn)
        async with lock:
            await self._transition_hook('activate_locked', conn.connection_key, conn)
            await self._register_connection(conn.connection_key, conn)
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

    async def _mark_offline_if_current(self, conn: ModuleConnection) -> bool:
        if not conn.connection_key:
            return False
        lock = await self._session_lock(conn.connection_key)
        async with lock:
            await self._transition_hook('offline_locked', conn.connection_key, conn)
            should_mark_offline = await self._unregister_connection(conn)
            if not should_mark_offline:
                return False
            async with db.acquire() as dbc:
                await dbc.execute('''
                    UPDATE modules
                    SET online=false,
                        control_session_online=false
                    WHERE ($1::text IS NOT NULL AND device_id=$1)
                       OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                ''', conn.device_id, conn.module_uuid)
            return True

    async def _assign(self, ident: dict[str, Any]) -> dict[str, Any]:
        typ = str(ident.get('module_type','')).upper()
        if typ not in MODULE_TYPES:
            raise ValueError(f'unsupported module type {typ}')
        device_id = self._device_id_from_ident(ident)
        module_uuid = ident.get('module_uuid')
        if not device_id and not module_uuid:
            raise ValueError('identify requires device_id or legacy module_uuid')
        identity_label = device_id or module_uuid
        lab1_device_id = maybe_normalize_device_id(settings.lab1_device_id)
        is_lab1 = device_id == lab1_device_id
        if is_lab1 and typ not in LAB1_SIMULATED_MODULE_TYPES:
            raise ValueError(f'LAB1 does not support simulated role {typ}')
        async with db.acquire() as conn:
            async with _transaction(conn):
                rows = await conn.fetch('''
                    SELECT id, hostname, ip_address, device_id, module_uuid::text AS module_uuid
                    FROM modules
                    WHERE ($1::text IS NOT NULL AND device_id=$1)
                       OR ($2::text IS NOT NULL AND module_uuid::text=$2)
                    FOR UPDATE
                ''', device_id, module_uuid)
                ids = {int(row['id']) for row in rows}
                if len(ids) > 1:
                    raise ValueError('identify maps to conflicting module records')
                if rows:
                    row = rows[0]
                    if device_id and row['device_id'] and row['device_id'] != device_id:
                        raise ValueError('device_id conflicts with existing module record')
                    if module_uuid and row['module_uuid'] and row['module_uuid'] != module_uuid:
                        raise ValueError('module_uuid conflicts with existing module record')
                    await conn.execute('''
                        UPDATE modules
                        SET device_id=COALESCE(device_id, $2),
                            module_uuid=COALESCE(module_uuid, $3::uuid),
                            identity_interface=COALESCE($4, identity_interface)
                        WHERE id=$1
                    ''',
                        row['id'],
                        device_id,
                        module_uuid,
                        ident.get('identity_interface') or (ident.get('identity') or {}).get('interface'),
                    )
                    return {'hostname': row['hostname'], 'ip_address': str(row['ip_address']), 'reboot_required': False}
                if not settings.commissioning_enabled:
                    raise PermissionError(f'commissioning disabled for unknown {typ} module {identity_label}')
                if is_lab1:
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
                        settings.lab1_hostname,
                        settings.lab1_ip_address,
                        ident.get('software_version'),
                    )
                    return {
                        'hostname': settings.lab1_hostname,
                        'ip_address': settings.lab1_ip_address,
                        'reboot_required': False,
                    }
                plan = load_control_network_plan()
                addresses = plan.addresses_for(typ)
                used = {str(r['ip_address']) for r in await conn.fetch('SELECT ip_address FROM modules WHERE module_type=$1', typ)}
                used.add(settings.lab1_ip_address)
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

    async def _base_config(self, module_type: str, logical_id: str | None = None, device_id: str | None = None) -> dict[str, Any]:
        path = Path(settings.config_root) / {
            'RCM':'04_RCM','LCM':'03_LCM','SIM':'02_SIM','PNL':'05_PNL'
        }[module_type] / f'{module_type.lower()}.yaml'
        if not path.exists():
            result = {'version': 1, 'config': {}}
        else:
            import yaml
            data = yaml.safe_load(path.read_text()) or {}
            result = {'version': int(data.get('config_version',1)), 'config': data}
        logical_id = logical_id or module_type
        result['package'] = module_infra.build_config_package(
            module_type,
            logical_id,
            result.get('config') or {},
            revision=str(result['version']),
        )
        result['heartbeat_supervisor'] = {
            'enabled': bool(settings.conflict_heartbeat_enabled),
            'device_id': maybe_normalize_device_id(settings.conflict_heartbeat_device_id),
            'host': settings.conflict_heartbeat_host,
            'port': int(settings.conflict_heartbeat_port),
            'interval_seconds': int(settings.conflict_heartbeat_interval_s),
            'timeout_seconds': int(settings.conflict_heartbeat_timeout_s),
            'protocol': settings.conflict_heartbeat_protocol,
        }
        if device_id:
            try:
                from .auth import build_user_snapshot
                result['user_snapshot'] = await build_user_snapshot(device_id)
            except Exception:
                log.warning('could not build user snapshot for %s', device_id, exc_info=True)
        return result

    def _stored_channel_config_payload(self, module_type: str, logical_id: str) -> dict[str, Any] | None:
        """Return the latest persisted channel package for reconnect replay."""
        config_path = storage.storage_root() / "config" / module_type.upper() / f"{logical_id}.json"
        sync_path = storage.storage_root() / ".state" / "config-sync" / f"{logical_id}.json"
        try:
            stored = json.loads(config_path.read_text())
            sync = json.loads(sync_path.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        config = stored.get("config")
        revision = sync.get("revision")
        if not isinstance(config, dict) or not isinstance(config.get("channels"), list) or not isinstance(revision, str):
            return None
        package = module_infra.build_config_package(module_type, logical_id, config, revision=revision)
        if sync.get("checksum") and package["checksum"] != sync["checksum"]:
            log.warning("stored configuration checksum mismatch for %s", logical_id)
            return None
        return {"package": package, "base_revision": None}

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
        if 'capabilities' not in ident:
            return
        capabilities = self._capability_rows(ident)
        row = await dbc.fetchrow('''
            SELECT id
            FROM modules
            WHERE ($1::text IS NOT NULL AND device_id=$1)
               OR ($2::text IS NOT NULL AND module_uuid::text=$2)
        ''', device_id, module_uuid)
        if not row:
            return
        module_id = int(row['id'])
        async with _transaction(dbc):
            if ident.get('capabilities_full_snapshot') is True:
                if capabilities:
                    await dbc.execute(
                        'DELETE FROM module_capabilities WHERE module_id=$1 AND NOT (capability=ANY($2::text[]))',
                        module_id,
                        [name for name, _details in capabilities],
                    )
                else:
                    await dbc.execute('DELETE FROM module_capabilities WHERE module_id=$1', module_id)
            for name, details in capabilities:
                await dbc.execute('''
                    INSERT INTO module_capabilities(module_id, capability, details, updated_at)
                    VALUES($1,$2,$3::jsonb,now())
                    ON CONFLICT(module_id, capability)
                    DO UPDATE SET details=EXCLUDED.details, updated_at=now()
                ''', module_id, name, json.dumps(details))

    @staticmethod
    def verify_client_identity(peercert, ident):
        """Bind an authenticated client certificate to its claimed device ID."""
        if not isinstance(ident, dict):
            raise protocol.ProtocolError('invalid identification payload')

        raw_id = ident.get('device_id')
        if not isinstance(raw_id, str):
            raise protocol.ProtocolError('certificate registration requires device_id')

        try:
            device_id = maybe_normalize_device_id(raw_id)
        except (TypeError, ValueError):
            raise protocol.ProtocolError('invalid device_id') from None

        if not isinstance(device_id, str) or not re.fullmatch(r'[0-9a-f]{12}', device_id):
            raise protocol.ProtocolError('invalid certificate device_id')

        if not isinstance(peercert, dict):
            raise protocol.ProtocolError('client certificate required')

        san = peercert.get('subjectAltName', ())
        if not isinstance(san, (tuple, list)):
            raise protocol.ProtocolError('invalid certificate SAN')

        if not all(isinstance(item, (tuple, list)) and len(item) == 2 for item in san):
            raise protocol.ProtocolError('invalid certificate SAN')

        uri_sans = [value for kind, value in san if kind == 'URI']
        device_uris = [
            value for value in uri_sans
            if isinstance(value, str) and value.startswith(DEVICE_URI_PREFIX)
        ]
        if len(device_uris) != 1:
            raise protocol.ProtocolError('client certificate requires exactly one device URI SAN')
        uri_device_id = device_uris[0][len(DEVICE_URI_PREFIX):]
        try:
            cert_device_id = maybe_normalize_device_id(uri_device_id)
        except InvalidDeviceId:
            raise protocol.ProtocolError('invalid certificate device URI SAN') from None

        if cert_device_id != device_id:
            raise protocol.ProtocolError('client certificate device identity mismatch')

        return device_id

    def _verified_ident(self, peercert, ident: dict[str, Any]) -> dict[str, Any]:
        if not self._certificate_identity_enforced():
            return ident
        device_id = self.verify_client_identity(peercert, ident)
        verified = dict(ident)
        verified['device_id'] = device_id
        return verified

    def _preserve_local_assignment(self, device_id: str | None) -> bool:
        return device_id == maybe_normalize_device_id(settings.lab1_device_id)

    async def _accept_module_config_update(self, conn: ModuleConnection, payload: dict[str, Any]) -> dict[str, Any]:
        package = payload.get('package') if isinstance(payload, dict) else None
        if not isinstance(package, dict):
            return {'ok': False, 'error': 'configuration package is required'}
        module_type = str(conn.module_type or '').upper()
        logical_id = str(conn.hostname or '')
        if module_type not in {'RCM', 'LCM'} or not logical_id:
            return {'ok': False, 'error': 'module configuration role is not authorized'}
        module_infra.verify_config_package(package, module_type=module_type, logical_id=logical_id)
        config = package.get('config')
        channels = config.get('channels') if isinstance(config, dict) else None
        if not isinstance(channels, list):
            return {'ok': False, 'error': 'channel configuration is required'}
        store = module_infra.LocalConfigStore(storage.storage_root(), module_type, logical_id)
        current = store.load_json()
        current_config = current.get('config') if isinstance(current.get('config'), dict) else {}
        sync_path = storage.storage_root() / '.state' / 'config-sync' / f'{logical_id}.json'
        try:
            sync_state = json.loads(sync_path.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            sync_state = {}
        current_revision = sync_state.get('revision')
        base_revision = payload.get('base_revision')
        if current_revision and base_revision != current_revision:
            return {'ok': False, 'error': 'configuration_conflict', 'current_revision': current_revision, 'base_revision': base_revision}
        merged, conflicts = module_infra.reconcile_lockouts(config, current_config)
        if module_type == 'RCM':
            csv_meta = store.save_rcm_csv(merged['channels'])
        else:
            csv_meta = store.save_lcm_csv(merged['channels'])
        accepted = module_infra.build_config_package(module_type, logical_id, merged, revision=csv_meta['revision'])
        sync = {
            'state': 'conflict' if conflicts else 'synchronized',
            'origin': 'local_emergency_config',
            'revision': accepted['revision'],
            'checksum': accepted['checksum'],
            'conflicts': conflicts,
            'updated_at': module_infra.utc_ts(),
        }
        store.save_json({**accepted, 'config_sync': sync})
        module_infra.atomic_write_text(sync_path, json.dumps({**sync, 'module_type': module_type, 'logical_id': logical_id}, indent=2, sort_keys=True))
        return {'ok': True, 'accepted': True, 'revision': accepted['revision'], 'checksum': accepted['checksum'], 'config_sync': sync}

    async def handle_client(self, reader, writer):
        conn = ModuleConnection(reader, writer)
        peer = writer.get_extra_info('peername')
        try:
            first = await protocol.read_frame(reader)
            if first.get('type') != 'identify':
                raise protocol.ProtocolError('first message must be identify')
            ident = first.get('payload', {})
            ident = self._verified_ident(writer.get_extra_info('peercert'), ident)
            conn.device_id = self._device_id_from_ident(ident)
            conn.module_uuid = ident.get('module_uuid')
            conn.module_type = str(ident.get('module_type') or '').upper()
            conn.connection_key = conn.device_id or conn.module_uuid
            assignment = await self._assign(ident)
            conn.hostname = assignment['hostname']
            await self._activate_connection(conn, ident)
            if (
                not self._preserve_local_assignment(conn.device_id)
                and (
                    ident.get('hostname') != assignment['hostname']
                    or ident.get('assigned_ip') != assignment['ip_address']
                )
            ):
                await conn.send('assignment', assignment)
            else:
                try:
                    config_payload = await self._base_config(ident['module_type'], assignment['hostname'], conn.device_id)
                except TypeError:
                    config_payload = await self._base_config(ident['module_type'])
                await conn.send('config', config_payload)
                stored_payload = self._stored_channel_config_payload(ident['module_type'], assignment['hostname'])
                if stored_payload:
                    await conn.send('config', stored_payload)

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
                    await role_switching.confirm_from_state(conn.device_id, payload)
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
                    await role_switching.confirm_from_state(conn.device_id, payload)
                elif typ == 'fault':
                    async with db.acquire() as dbc:
                        await dbc.execute('''INSERT INTO faults(device_id,module_uuid,code,severity,details) VALUES($1,$2,$3,$4,$5::jsonb)''', conn.device_id, conn.module_uuid, payload.get('code','unknown'), payload.get('severity','warning'), json.dumps(payload))
                elif typ == 'log_events':
                    event_ids = await self._ingest_log_events(conn, payload)
                    await conn.send('log_ack', {'event_ids': event_ids})
                elif typ == 'config':
                    try:
                        ack = await self._accept_module_config_update(conn, payload)
                    except (ValueError, KeyError) as exc:
                        ack = {'ok': False, 'error': str(exc)}
                    await conn.send('command_ack', ack, msg.get('request_id'))
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
                try:
                    await self._mark_offline_if_current(conn)
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
        async with self._connections_lock:
            mc = self.connections.get(key)
        if not mc: raise ConnectionError(f'{hostname} offline')
        return await mc.command(payload, timeout=timeout)

    async def config_by_hostname(self, hostname: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        async with db.acquire() as conn:
            row = await conn.fetchrow('SELECT device_id, module_uuid::text AS module_uuid FROM modules WHERE hostname=$1', hostname)
        if not row:
            raise KeyError(hostname)
        key = row['device_id'] or str(row['module_uuid'])
        async with self._connections_lock:
            mc = self.connections.get(key)
        if not mc:
            raise ConnectionError(f'{hostname} offline')
        return await mc.config(payload, timeout=timeout)

    async def _ingest_log_events(self, conn: ModuleConnection, payload: dict[str, Any]) -> list[str]:
        events = payload.get('events') or []
        if not isinstance(events, list):
            return []
        root = storage.storage_root()
        logical = conn.hostname or conn.device_id or conn.module_uuid or 'unknown-module'
        log_dir = root / 'logs' / str(logical)
        log_dir.mkdir(parents=True, exist_ok=True)
        index_path = log_dir / 'delivered-event-ids.json'
        try:
            delivered = set(json.loads(index_path.read_text()))
        except (OSError, json.JSONDecodeError):
            delivered = set()
        accepted: list[str] = []
        with (log_dir / 'events.jsonl').open('a', encoding='utf-8') as handle:
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get('event_id') or '')
                if not event_id or event_id in delivered:
                    accepted.append(event_id)
                    continue
                safe_event = {
                    key: value
                    for key, value in event.items()
                    if not any(secret in key.lower() for secret in ('password', 'token', 'secret', 'credential'))
                }
                handle.write(json.dumps(safe_event, sort_keys=True) + '\n')
                delivered.add(event_id)
                accepted.append(event_id)
        module_infra.atomic_write_text(index_path, json.dumps(sorted(delivered), indent=2))
        return accepted

registry = ModuleRegistry()
