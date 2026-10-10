import asyncio
from pathlib import Path
from importlib import import_module
import json

import pytest

registry_mod = import_module('01_HCM.registry')
protocol = import_module('07_servises.common.protocol')


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
        elif 'INSERT INTO module_capabilities' in query:
            module_id, capability, details = args
            for row in self.modules.values():
                if row['id'] == module_id:
                    row.setdefault('capabilities', {})[capability] = details
                    break
        elif 'DELETE FROM module_capabilities' in query:
            module_id, capabilities = args
            for row in self.modules.values():
                if row['id'] == module_id:
                    existing = row.setdefault('capabilities', {})
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
