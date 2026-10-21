import asyncio
from pathlib import Path
from importlib import import_module
import json

import pytest

registry_mod = import_module('01_HCM.registry')
protocol = import_module('08_servises.common.protocol')


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeRegistryConn:
    def __init__(self):
        self.modules = {}
        self.executed = []

    async def fetchrow(self, query, *args):
        if 'SELECT id' in query and 'FROM modules' in query:
            device_id, module_uuid = args
            row = self._find(device_id, module_uuid)
            if not row:
                return None
            return {'id': row['id']}
        if 'device_id=$1' in query and 'module_uuid::text=$2' in query:
            device_id, module_uuid = args
            row = None
            if device_id:
                row = next((r for r in self.modules.values() if r.get('device_id') == device_id), None)
            if row is None and module_uuid:
                row = self.modules.get(module_uuid)
            if not row:
                return None
            return {'hostname': row['hostname'], 'ip_address': row['ip_address']}
        if 'WHERE hostname=$1' in query:
            for module_uuid, row in self.modules.items():
                if row['hostname'] == args[0]:
                    return {'device_id': row.get('device_id'), 'module_uuid': module_uuid}
            return None
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def fetch(self, query, *args):
        if 'SELECT id, hostname, ip_address, device_id' in query:
            device_id, module_uuid = args
            rows = []
            for key, row in self.modules.items():
                if (device_id and row.get('device_id') == device_id) or (module_uuid and key == module_uuid):
                    row.setdefault('id', len(rows) + 1)
                    rows.append({
                        'id': row['id'],
                        'hostname': row['hostname'],
                        'ip_address': row['ip_address'],
                        'device_id': row.get('device_id'),
                        'module_uuid': key if key != row.get('device_id') else row.get('module_uuid'),
                    })
            return rows
        if 'SELECT ip_address FROM modules WHERE module_type=$1' in query:
            return [
                {'ip_address': row['ip_address']}
                for row in self.modules.values()
                if row['module_type'] == args[0]
            ]
        raise AssertionError(f'unexpected fetch: {query}')

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if 'INSERT INTO modules' in query:
            device_id, module_uuid, identity_interface, module_type, hostname, ip_address, software_version = args
            key = module_uuid or device_id
            self.modules[key] = {
                'id': len(self.modules) + 1,
                'device_id': device_id,
                'identity_interface': identity_interface,
                'module_type': module_type,
                'hostname': hostname,
                'ip_address': ip_address,
                'software_version': software_version,
                'online': True,
                'control_session_online': True,
            }
        elif 'last_state=$3::jsonb' in query and 'online=true' in query:
            device_id, module_uuid, state = args
            row = self._find(device_id, module_uuid)
            if row:
                row['last_state'] = state
                row['online'] = True
                row['control_session_online'] = True
        elif 'SET online=true' in query:
            device_id, module_uuid = args[:2]
            row = self._find(device_id, module_uuid)
            if row:
                row['online'] = True
                row['control_session_online'] = True
                if len(args) > 2:
                    row['software_version'] = args[2]
                    row['identity_interface'] = args[3] or row.get('identity_interface')
        elif 'SET device_id=COALESCE' in query:
            module_id, device_id, module_uuid, identity_interface = args
            for key, row in list(self.modules.items()):
                if row['id'] == module_id:
                    row['device_id'] = row.get('device_id') or device_id
                    row['module_uuid'] = row.get('module_uuid') or module_uuid
                    row['identity_interface'] = identity_interface or row.get('identity_interface')
                    if module_uuid and key != module_uuid:
                        self.modules[module_uuid] = row
                    break
        elif 'INSERT INTO module_capabilities' in query:
            module_id, capability, details = args
            for row in self.modules.values():
                if row['id'] == module_id:
                    row.setdefault('capabilities', {})[capability] = details
                    break
        elif 'DELETE FROM module_capabilities' in query:
            module_id = args[0]
            for row in self.modules.values():
                if row['id'] == module_id:
                    existing = row.setdefault('capabilities', {})
                    if len(args) == 1:
                        existing.clear()
                    else:
                        capabilities = args[1]
                        for capability in list(existing):
                            if capability not in capabilities:
                                existing.pop(capability, None)
                    break
        elif 'online=false' in query and 'UPDATE modules' in query:
            device_id, module_uuid = args
            row = self._find(device_id, module_uuid)
            if row:
                row['online'] = False
                row['control_session_online'] = False
        else:
            raise AssertionError(f'unexpected execute: {query}')

    def _find(self, device_id, module_uuid):
        if module_uuid in self.modules:
            return self.modules[module_uuid]
        if device_id:
            return next((row for row in self.modules.values() if row.get('device_id') == device_id), None)
        return None


LAB1_CERT = {
    'subjectAltName': (
        ('URI', 'urn:homecontrol:device:2ccf675d3414'),
    )
}


class BlockingRegistryConn(FakeRegistryConn):
    def __init__(self):
        super().__init__()
        self.events = []
        self.offline_started = asyncio.Event()
        self.release_offline = asyncio.Event()

    async def execute(self, query, *args):
        if 'online=false' in query and 'UPDATE modules' in query:
            self.events.append('offline-start')
            self.offline_started.set()
            await self.release_offline.wait()
            await super().execute(query, *args)
            self.events.append('offline-finish')
            return
        if 'SET online=true' in query:
            self.events.append('online')
        await super().execute(query, *args)


@pytest.mark.asyncio
async def test_assign_uses_configured_development_control_network(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    first = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-a', 'software_version': '0.1'})
    second = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-b', 'software_version': '0.1'})
    lcm = await reg._assign({'module_type': 'LCM', 'module_uuid': 'lcm-a', 'software_version': '0.1'})

    assert first == {'hostname': 'RCM01', 'ip_address': '192.168.20.20', 'reboot_required': True}
    assert second == {'hostname': 'RCM02', 'ip_address': '192.168.20.21', 'reboot_required': True}
    assert lcm == {'hostname': 'LCM01', 'ip_address': '192.168.20.30', 'reboot_required': True}


@pytest.mark.asyncio
async def test_base_config_includes_conflict_heartbeat_supervisor(monkeypatch, tmp_path):
    monkeypatch.setattr(registry_mod.settings, 'config_root', tmp_path)
    monkeypatch.setattr(registry_mod.settings, 'conflict_heartbeat_device_id', '3c:53:bb:f7:ad:b2')
    monkeypatch.setattr(registry_mod.settings, 'conflict_heartbeat_host', '192.168.20.26')
    reg = registry_mod.ModuleRegistry()

    payload = await reg._base_config('SIM')

    assert payload['heartbeat_supervisor'] == {
        'enabled': True,
        'device_id': '3c53bbf7adb2',
        'host': '192.168.20.26',
        'port': 6004,
        'interval_seconds': 5,
        'timeout_seconds': 15,
        'protocol': 'hcm-heartbeat-v3',
    }
    assert payload['package']['module_type'] == 'SIM'
    assert payload['package']['checksum']


def test_stored_channel_config_payload_rebuilds_package_from_hcm_revision(monkeypatch, tmp_path):
    reg = registry_mod.ModuleRegistry()
    monkeypatch.setattr(registry_mod.storage, 'storage_root', lambda: tmp_path)
    store = registry_mod.module_infra.LocalConfigStore(tmp_path, 'RCM', 'lab1')
    config = {'channels': registry_mod.module_infra.default_rcm_config()}
    csv_meta = store.save_rcm_csv(config['channels'])
    package = registry_mod.module_infra.build_config_package('RCM', 'lab1', config, revision=csv_meta['revision'])
    store.save_json(package)
    sync_dir = tmp_path / '.state' / 'config-sync'
    sync_dir.mkdir(parents=True)
    (sync_dir / 'lab1.json').write_text(json.dumps({'revision': package['revision'], 'checksum': package['checksum']}))

    payload = reg._stored_channel_config_payload('RCM', 'lab1')

    assert payload['package']['revision'] == csv_meta['revision']
    assert payload['package']['checksum'] == package['checksum']


@pytest.mark.asyncio
async def test_registry_ingests_module_logs_durably_and_deduplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(registry_mod.storage.settings, 'storage_root', tmp_path)
    reg = registry_mod.ModuleRegistry()
    conn = registry_mod.ModuleConnection(None, None)
    conn.hostname = 'RCM1'

    first = await reg._ingest_log_events(conn, {'events': [
        {'event_id': 'evt-1', 'message': 'first', 'token': 'secret'},
        {'event_id': 'evt-1', 'message': 'duplicate'},
    ]})
    second = await reg._ingest_log_events(conn, {'events': [{'event_id': 'evt-1', 'message': 'again'}]})

    log_path = tmp_path / 'logs' / 'RCM1' / 'events.jsonl'
    lines = log_path.read_text().splitlines()
    assert first == ['evt-1', 'evt-1']
    assert second == ['evt-1']
    assert len(lines) == 1
    assert 'secret' not in lines[0]


@pytest.mark.asyncio
async def test_config_by_hostname_uses_authenticated_module_session(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['rcm-a'] = {
        'id': 1,
        'device_id': '48b02d87db10',
        'module_uuid': 'rcm-a',
        'module_type': 'RCM',
        'hostname': 'RCM1',
        'ip_address': '192.168.20.31',
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    class FakeModuleConnection:
        async def config(self, payload, timeout=10.0):
            return {'ok': True, 'applied': payload['package']['revision']}

    reg.connections['48b02d87db10'] = FakeModuleConnection()
    result = await reg.config_by_hostname('RCM1', {'package': {'revision': 'rev-1'}})

    assert result == {'ok': True, 'applied': 'rev-1'}


@pytest.mark.asyncio
async def test_assign_prefers_normalized_device_id(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    assignment = await reg._assign({
        'module_type': 'RCM',
        'device_id': '48:b0:2d:87:db:16',
        'module_uuid': 'legacy-uuid',
        'software_version': '0.1',
    })

    assert assignment == {'hostname': 'RCM01', 'ip_address': '192.168.20.20', 'reboot_required': True}
    assert conn.modules['legacy-uuid']['device_id'] == '48b02d87db16'


@pytest.mark.asyncio
async def test_identify_capabilities_are_normalized_for_persistence(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    await reg._assign({
        'module_type': 'SIM',
        'device_id': '48:b0:2d:87:db:16',
        'identity_interface': 'eth0',
        'capabilities': [
            'telemetry',
            {'name': 'rmc-can', 'interfaces': ['can0']},
            {'capability': 'hexa-dio', 'channels': 4},
            'telemetry',
        ],
    })
    async with registry_mod.db.acquire() as dbc:
        await reg._store_capabilities(dbc, '48b02d87db16', None, {
            'capabilities': [
                'telemetry',
                {'name': 'rmc-can', 'interfaces': ['can0']},
                {'capability': 'hexa-dio', 'channels': 4},
                'telemetry',
            ],
        })

    capabilities = conn.modules['48b02d87db16']['capabilities']
    assert set(capabilities) == {'telemetry', 'rmc-can', 'hexa-dio'}
    assert json.loads(capabilities['rmc-can']) == {'interfaces': ['can0']}
    assert conn.modules['48b02d87db16']['identity_interface'] == 'eth0'


@pytest.mark.asyncio
async def test_partial_capability_reports_do_not_delete_existing_capabilities(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()
    await reg._assign({'module_type': 'SIM', 'device_id': '48:b0:2d:87:db:16'})
    conn.modules['48b02d87db16']['capabilities'] = {'telemetry': '{}', 'rmc-can': '{}'}

    async with registry_mod.db.acquire() as dbc:
        await reg._store_capabilities(dbc, '48b02d87db16', None, {
            'capabilities': ['telemetry'],
        })

    assert set(conn.modules['48b02d87db16']['capabilities']) == {'telemetry', 'rmc-can'}


@pytest.mark.asyncio
async def test_full_capability_snapshot_replaces_existing_capabilities(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()
    await reg._assign({'module_type': 'SIM', 'device_id': '48:b0:2d:87:db:16'})
    conn.modules['48b02d87db16']['capabilities'] = {'telemetry': '{}', 'rmc-can': '{}'}

    async with registry_mod.db.acquire() as dbc:
        await reg._store_capabilities(dbc, '48b02d87db16', None, {
            'capabilities_full_snapshot': True,
            'capabilities': ['telemetry'],
        })

    assert set(conn.modules['48b02d87db16']['capabilities']) == {'telemetry'}


@pytest.mark.asyncio
async def test_assign_rejects_conflicting_device_id_and_legacy_uuid(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['legacy-a'] = {
        'id': 1,
        'device_id': None,
        'module_type': 'RCM',
        'hostname': 'RCM01',
        'ip_address': '192.168.20.20',
        'online': False,
    }
    conn.modules['legacy-b'] = {
        'id': 2,
        'device_id': '48b02d87db16',
        'module_type': 'RCM',
        'hostname': 'RCM02',
        'ip_address': '192.168.20.21',
        'online': False,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(ValueError, match='conflicting module records'):
        await reg._assign({
            'module_type': 'RCM',
            'device_id': '48:b0:2d:87:db:16',
            'module_uuid': 'legacy-a',
        })


@pytest.mark.asyncio
async def test_old_connection_cannot_remove_newer_connection():
    reg = registry_mod.ModuleRegistry()
    old = registry_mod.ModuleConnection(None, None)
    old.connection_key = '48b02d87db16'
    new = registry_mod.ModuleConnection(None, None)
    new.connection_key = '48b02d87db16'

    await reg._register_connection(old.connection_key, old)
    await reg._register_connection(new.connection_key, new)

    assert await reg._unregister_connection(old) is False
    assert reg.connections['48b02d87db16'] is new
    assert await reg._unregister_connection(new) is True
    assert '48b02d87db16' not in reg.connections


@pytest.mark.asyncio
async def test_replaced_connection_cannot_mark_new_session_offline(monkeypatch):
    key = '48b02d87db16'
    conn = BlockingRegistryConn()
    conn.modules[key] = {
        'id': 1,
        'device_id': key,
        'module_type': 'LCM',
        'hostname': 'LCM01',
        'ip_address': '192.168.20.30',
        'online': True,
        'control_session_online': True,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))

    reg = registry_mod.ModuleRegistry()
    old = registry_mod.ModuleConnection(None, None)
    old.device_id = key
    old.connection_key = key
    new = registry_mod.ModuleConnection(None, None)
    new.device_id = key
    new.connection_key = key
    await reg._register_connection(key, old)

    activate_waiting = asyncio.Event()
    release_activate = asyncio.Event()

    async def transition_hook(event, hook_key, hook_conn):
        if event == 'activate_waiting' and hook_key == key and hook_conn is new:
            activate_waiting.set()
            await release_activate.wait()

    reg._session_transition_hook = transition_hook

    offline_task = asyncio.create_task(reg._mark_offline_if_current(old))
    await conn.offline_started.wait()
    activate_task = asyncio.create_task(reg._activate_connection(new, {'software_version': '0.2'}))
    await activate_waiting.wait()

    assert reg.connections.get(key) is None
    assert conn.modules[key]['online'] is True

    release_activate.set()
    conn.release_offline.set()
    assert await offline_task is True
    await activate_task

    assert conn.events == ['offline-start', 'offline-finish', 'online']
    assert reg.connections[key] is new
    assert conn.modules[key]['online'] is True
    assert conn.modules[key]['control_session_online'] is True


def write_hcm_config(root: Path, active_profile: str, production_subnet: str | None = None) -> None:
    path = root / '01_HCM'
    path.mkdir(parents=True)
    prod_subnet = production_subnet if production_subnet is not None else 'null'
    prod_enabled = 'true' if production_subnet else 'false'
    (path / 'hcm.yaml').write_text(f'''
network:
  control:
    active_profile: {active_profile}
    profiles:
      development_control:
        vlan: 20
        subnet: 192.168.20.0/24
        assignment_enabled: true
        pools:
          RCM: {{start: 192.168.20.20, end: 192.168.20.29}}
          LCM: {{start: 192.168.20.30, end: 192.168.20.39}}
          SIM: {{start: 192.168.20.40, end: 192.168.20.49}}
          PNL: {{start: 192.168.20.50, end: 192.168.20.89}}
      production_control:
        vlan: 40
        subnet: {prod_subnet}
        assignment_enabled: {prod_enabled}
        require_explicit_subnet: true
        pools:
          RCM: {{start: 192.168.40.20, end: 192.168.40.29}}
''')


def test_future_production_control_requires_explicit_subnet(tmp_path, monkeypatch):
    write_hcm_config(tmp_path, 'production_control')
    monkeypatch.setattr(registry_mod.settings, 'config_root', tmp_path)

    with pytest.raises(RuntimeError, match='requires an approved subnet'):
        registry_mod.load_control_network_plan()


def test_vlan60_rejected_as_control_network(tmp_path, monkeypatch):
    root = tmp_path / 'cfg'
    path = root / '01_HCM'
    path.mkdir(parents=True)
    (path / 'hcm.yaml').write_text('''
network:
  control:
    active_profile: bad_control
    profiles:
      bad_control:
        vlan: 60
        subnet: 192.168.60.0/24
        pools:
          RCM: {start: 192.168.60.20, end: 192.168.60.29}
''')
    monkeypatch.setattr(registry_mod.settings, 'config_root', root)

    with pytest.raises(RuntimeError, match='VLAN 60 is reserved'):
        registry_mod.load_control_network_plan()


@pytest.mark.asyncio
async def test_assign_existing_module_keeps_identity(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['rcm-a'] = {
        'device_id': None,
        'module_type': 'RCM',
        'hostname': 'RCM01',
        'ip_address': '192.168.60.20',
        'online': False,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', False)
    reg = registry_mod.ModuleRegistry()

    assignment = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-a', 'software_version': '0.2'})

    assert assignment == {'hostname': 'RCM01', 'ip_address': '192.168.60.20', 'reboot_required': False}


@pytest.mark.asyncio
async def test_assign_rejects_unknown_module_when_commissioning_disabled(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', False)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(PermissionError):
        await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-new', 'software_version': '0.1'})


def test_mutual_tls_requires_ca(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_cert', '/tmp/cert.pem')
    monkeypatch.setattr(registry_mod.settings, 'tls_key', '/tmp/key.pem')
    monkeypatch.setattr(registry_mod.settings, 'tls_ca', None)
    monkeypatch.setattr(registry_mod.settings, 'tls_require_client_cert', True)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(RuntimeError, match='HCM_TLS_CA'):
        reg._ssl_context()


def test_module_listener_rejects_published_insecure_configuration(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, 'allow_insecure_module_listener', False)
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', False)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(RuntimeError, match='requires TLS'):
        reg._validate_module_listener_security()


def test_module_listener_allows_explicit_local_insecure_configuration(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, 'allow_insecure_module_listener', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', False)
    reg = registry_mod.ModuleRegistry()

    reg._validate_module_listener_security()


def test_module_listener_requires_certificate_identity_in_secure_mode(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, 'allow_insecure_module_listener', False)
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_require_client_cert', True)
    monkeypatch.setattr(registry_mod.settings, 'module_cert_identity_required', False)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(RuntimeError, match='device identity'):
        reg._validate_module_listener_security()


@pytest.mark.asyncio
async def test_lab1_commissioning_preserves_hostname_and_ip(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    assignment = await reg._assign({
        'module_type': 'LCM',
        'device_id': '2c:cf:67:5d:34:14',
        'hostname': 'LAB1-old',
        'assigned_ip': '192.168.20.99',
        'software_version': 'lab',
    })

    assert assignment == {
        'hostname': 'lab1',
        'ip_address': '192.168.20.36',
        'reboot_required': False,
    }
    module = conn._find('2ccf675d3414', None)
    assert module['hostname'] == 'lab1'
    assert module['ip_address'] == '192.168.20.36'
    assert module['module_type'] == 'LCM'


@pytest.mark.asyncio
async def test_lab1_rejects_unassigned_as_physical_module_role(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(ValueError, match='unsupported module type'):
        await reg._assign({
            'module_type': 'UNASSIGNED',
            'device_id': '2ccf675d3414',
        })


@pytest.mark.asyncio
async def test_lab1_rejects_roles_outside_simulator_allowlist(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(ValueError, match='LAB1 does not support'):
        await reg._assign({
            'module_type': 'PNL',
            'device_id': '2ccf675d3414',
        })


@pytest.mark.asyncio
async def test_regular_lcm_assignment_skips_lab1_reserved_ip(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    assignments = [
        await reg._assign({'module_type': 'LCM', 'device_id': f'48b02d87db1{i}'})
        for i in range(7)
    ]

    assert '192.168.20.36' not in {item['ip_address'] for item in assignments}


@pytest.mark.asyncio
async def test_registered_module_receives_config_and_heartbeat_ack(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['rcm-a'] = {
        'device_id': None,
        'module_type': 'RCM',
        'hostname': 'RCM01',
        'ip_address': '192.168.60.20',
        'online': False,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    async def base_config(module_type):
        return {'version': 7, 'config': {'module_type': module_type}}

    monkeypatch.setattr(reg, '_base_config', base_config)
    server = await asyncio.start_server(reg.handle_client, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    await protocol.write_frame(writer, {
        'type': 'identify',
        'payload': {
            'module_type': 'RCM',
            'module_uuid': 'rcm-a',
            'hostname': 'RCM01',
            'assigned_ip': '192.168.60.20',
            'software_version': '0.2',
        },
    })
    reply = await protocol.read_frame(reader)
    await protocol.write_frame(writer, {
        'type': 'heartbeat',
        'payload': {'module_uuid': 'rcm-a', 'state': {'relays': {}}},
    })
    ack = await protocol.read_frame(reader)

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()

    assert reply == {'type': 'config', 'payload': {'version': 7, 'config': {'module_type': 'RCM'}}}
    assert ack['type'] == 'heartbeat_ack'
    assert conn.modules['rcm-a']['last_state'] == '{"module_uuid": "rcm-a", "state": {"relays": {}}}'


@pytest.mark.asyncio
async def test_registration_handler_accepts_matching_client_certificate(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_require_client_cert', True)
    monkeypatch.setattr(registry_mod.settings, 'module_cert_identity_required', True)
    reg = registry_mod.ModuleRegistry()

    async def base_config(module_type):
        return {'version': 1, 'config': {'module_type': module_type}}

    original_get_extra_info = asyncio.StreamWriter.get_extra_info

    def get_extra_info(self, name, default=None):
        if name == 'peercert':
            return LAB1_CERT
        return original_get_extra_info(self, name, default)

    monkeypatch.setattr(asyncio.StreamWriter, 'get_extra_info', get_extra_info)
    monkeypatch.setattr(reg, '_base_config', base_config)
    server = await asyncio.start_server(reg.handle_client, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    await protocol.write_frame(writer, {
        'type': 'identify',
        'payload': {
            'module_type': 'LCM',
            'device_id': '2c:cf:67:5d:34:14',
            'hostname': 'LAB1-stale',
            'assigned_ip': '192.168.20.99',
            'software_version': 'lab',
        },
    })
    reply = await protocol.read_frame(reader)

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()

    assert reply == {'type': 'config', 'payload': {'version': 1, 'config': {'module_type': 'LCM'}}}
    assert conn._find('2ccf675d3414', None)['hostname'] == 'lab1'


@pytest.mark.asyncio
async def test_registration_handler_rejects_certificate_impersonation_before_db_write(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_require_client_cert', True)
    monkeypatch.setattr(registry_mod.settings, 'module_cert_identity_required', True)
    reg = registry_mod.ModuleRegistry()

    original_get_extra_info = asyncio.StreamWriter.get_extra_info

    def get_extra_info(self, name, default=None):
        if name == 'peercert':
            return LAB1_CERT
        return original_get_extra_info(self, name, default)

    monkeypatch.setattr(asyncio.StreamWriter, 'get_extra_info', get_extra_info)
    server = await asyncio.start_server(reg.handle_client, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    await protocol.write_frame(writer, {
        'type': 'identify',
        'payload': {
            'module_type': 'LCM',
            'device_id': '48:b0:2d:87:db:16',
            'hostname': 'LCM01',
            'assigned_ip': '192.168.20.30',
        },
    })

    with pytest.raises(asyncio.IncompleteReadError):
        await protocol.read_frame(reader)
    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()

    assert conn.executed == []
    assert conn.modules == {}
