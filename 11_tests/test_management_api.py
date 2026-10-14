from importlib import import_module
import json
import time

import pytest
from fastapi import HTTPException

api = import_module('01_HCM.api')
management = import_module('01_HCM.management')


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_host_network_status_file_rejects_stale_provider_data(monkeypatch, tmp_path):
    path = tmp_path / 'host-network-status.json'
    path.write_text(json.dumps({
        'updated_at': time.time() - 121,
        'interfaces': [{'name': 'eth0', 'ipv4': ['192.168.20.27/24']}],
    }))
    monkeypatch.setattr(management.settings, 'host_network_status_file', path)

    interfaces, reason = management._host_interfaces_from_status_file()

    assert interfaces == []
    assert reason == 'Configured host network status is stale'


def test_emergency_capability_rejects_unapproved_port_and_paths():
    module = {
        'device_id': '2ccf675d3414',
        'online': True,
        'ip_address': '192.168.20.36',
        'last_state': {'state': {'emergency_ui': {
            'enabled': True, 'available': True, 'protocol': 'http',
            'port': 8080, 'config_path': '/config', 'health_path': '/health',
        }}},
    }

    capability, reason = management._emergency_capability(module)

    assert capability is None
    assert 'invalid' in reason


@pytest.mark.asyncio
async def test_emergency_probe_binds_health_identity_and_constructs_config_url(monkeypatch):
    module = {
        'device_id': '2ccf675d3414',
        'online': True,
        'ip_address': '192.168.20.36',
        'last_state': {'state': {'emergency_ui': {
            'enabled': True, 'available': True, 'protocol': 'http',
            'port': 6010, 'config_path': '/config', 'health_path': '/health',
        }}},
    }

    class Response:
        status_code = 200

        def json(self):
            return {'identity': {'device_id': '2ccf675d3414'}}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            assert url == 'http://192.168.20.36:6010/health'
            return Response()

    monkeypatch.setattr(management.httpx, 'AsyncClient', Client)

    result = await management._probe_emergency_interface(module)

    assert result == {
        'available': True,
        'status': 'available',
        'url': 'http://192.168.20.36:6010/config',
        'reason': 'Verified module-advertised emergency service',
    }


@pytest.mark.asyncio
async def test_emergency_probe_rejects_wrong_health_identity(monkeypatch):
    module = {
        'device_id': '2ccf675d3414', 'online': True, 'ip_address': '192.168.20.36',
        'last_state': {'emergency_ui': {
            'enabled': True, 'available': True, 'protocol': 'http',
            'port': 6010, 'config_path': '/config', 'health_path': '/health',
        }},
    }

    class Response:
        status_code = 200
        def json(self):
            return {'identity': {'device_id': '001122334455'}}

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url): return Response()

    monkeypatch.setattr(management.httpx, 'AsyncClient', Client)
    result = await management._probe_emergency_interface(module)

    assert result['available'] is False
    assert result['status'] == 'unavailable'


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.transaction_depth += 1

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.transaction_depth -= 1
        return False


class FakeManagementConn:
    def __init__(self):
        self.logical_devices = {}
        self.modules = {
            1: {
                'id': 1,
                'device_id': '48b02d87db16',
                'module_uuid': None,
                'identity_interface': 'eth0',
                'module_type': 'LCM',
                'hostname': 'LCM01',
                'ip_address': '192.168.20.30',
                'heartbeat_ip': None,
                'online': True,
                'control_session_online': True,
                'supervision_state': 'unknown',
                'supervision_last_seen': None,
                'supervision_fresh_until': None,
                'last_health': {},
                'hardware_revision': None,
                'software_version': '0.1.0',
                'config_version': 1,
                'last_seen': None,
                'last_state': {},
                'commissioned_at': None,
            }
        }
        self.bindings = {}
        self.audit_events = []
        self.transaction_depth = 0
        self.capabilities = {1: {'analog-out-8', 'lighting'}}

    def transaction(self):
        return FakeTransaction(self)

    async def fetch(self, query, *args):
        if 'FROM modules' in query:
            return list(self.modules.values())
        if 'FROM module_capabilities' in query:
            return [{'capability': cap} for cap in sorted(self.capabilities.get(args[0], set()))]
        if 'FROM logical_devices' in query:
            return list(self.logical_devices.values())
        if 'FROM device_bindings' in query:
            return list(self.bindings.values())
        raise AssertionError(f'unexpected fetch: {query}')

    async def fetchrow(self, query, *args):
        if 'INSERT INTO logical_devices' in query:
            logical_name, room_id, device_class, enabled, metadata = args
            row = {
                'id': len(self.logical_devices) + 1,
                'logical_name': logical_name,
                'room_id': room_id,
                'room': None,
                'device_class': device_class,
                'enabled': enabled,
                'maintenance_locked': False,
                'metadata': json.loads(metadata),
            }
            self.logical_devices[logical_name] = row
            return row
        if 'SELECT *, NULL::text AS room FROM logical_devices WHERE logical_name=$1' in query:
            return self.logical_devices.get(args[0])
        if 'SELECT id FROM logical_devices WHERE logical_name=$1' in query:
            row = self.logical_devices.get(args[0])
            return {'id': row['id']} if row else None
        if 'UPDATE logical_devices' in query:
            current = self.logical_devices.pop(args[0])
            logical_name = args[1] or current['logical_name']
            current.update({
                'logical_name': logical_name,
                'device_class': args[2] or current['device_class'],
                'room_id': args[4] if args[3] else current['room_id'],
                'enabled': args[5] if args[5] is not None else current['enabled'],
                'maintenance_locked': args[6] if args[6] is not None else current['maintenance_locked'],
                'metadata': json.loads(args[7]) if args[7] is not None else current['metadata'],
            })
            self.logical_devices[logical_name] = current
            return current
        if 'SELECT id, hostname, module_type, device_id' in query and 'FROM modules' in query:
            text, device_id = args
            for row in self.modules.values():
                if str(row['id']) == text or row['hostname'] == text or row['device_id'] == device_id:
                    return {
                        'id': row['id'],
                        'hostname': row['hostname'],
                        'module_type': row['module_type'],
                        'device_id': row['device_id'],
                    }
            return None
        if 'SELECT id' in query and 'FROM modules' in query:
            text, device_id = args
            for row in self.modules.values():
                if str(row['id']) == text or row['hostname'] == text or row['device_id'] == device_id:
                    return {'id': row['id']}
            return None
        if 'SELECT id' in query and 'FROM device_bindings' in query:
            module_id, channel, binding_type, exclude_id = args
            for row in self.bindings.values():
                if row['module_id'] != module_id or not row['enabled'] or (exclude_id and row['id'] == exclude_id):
                    continue
                if channel is not None and row['channel'] == channel:
                    return {'id': row['id']}
                if channel is None and row['channel'] is None and row['binding_type'] == binding_type:
                    return {'id': row['id']}
            return None
        if 'INSERT INTO device_bindings' in query:
            logical_device_id, module_id, channel, binding_type, enabled, metadata = args
            row = {
                'id': len(self.bindings) + 1,
                'logical_device_id': logical_device_id,
                'module_id': module_id,
                'channel': channel,
                'binding_type': binding_type,
                'enabled': enabled,
                'metadata': json.loads(metadata),
            }
            self.bindings[row['id']] = row
            return row
        if 'FROM device_bindings b' in query and 'WHERE b.id=$1' in query:
            row = self.bindings.get(args[0])
            if not row:
                return None
            logical = next(v for v in self.logical_devices.values() if v['id'] == row['logical_device_id'])
            module = self.modules[row['module_id']]
            return {
                **row,
                'logical_name': logical['logical_name'],
                'hostname': module['hostname'],
                'device_id': module['device_id'],
                'module_type': module['module_type'],
            }
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def execute(self, query, *args):
        if 'INSERT INTO device_management_events' in query:
            self.audit_events.append(args)
            return
        if 'UPDATE device_bindings' in query:
            row = self.bindings[args[0]]
            if args[1] is not None:
                row['channel'] = args[1]
            if args[2] is not None:
                row['binding_type'] = args[2]
            if args[3] is not None:
                row['enabled'] = args[3]
            if args[4] is not None:
                row['metadata'] = json.loads(args[4])
            return
        raise AssertionError(f'unexpected execute: {query}')


def test_lcm_physical_channel_inventory_is_8_relays_10_lv_and_4_hv():
    assert management._lcm_light_channels() == [f'A{i}' for i in range(1, 9)]
    assert management._lcm_dimmer_channels() == [f'10-{i}' for i in range(1, 11)] + [f'HV-{i}' for i in range(1, 5)]
    assert len(management._lcm_channel_ids()) == 22


def test_lcm_channel_support_accepts_corrected_inventory_without_direct_hardware_route():
    capabilities = {'lighting'}

    assert management._module_supports_channel('LCM', 'A8', capabilities) is True
    assert management._module_supports_channel('LCM', 'B1', capabilities) is False
    assert management._module_supports_channel('LCM', '10-10', capabilities) is True
    assert management._module_supports_channel('LCM', '10-11', capabilities) is False
    assert management._module_supports_channel('LCM', 'HV-4', capabilities) is True


def test_rcm_config_from_channels_preserves_commanded_state_not_feedback():
    channels = [
        {'channel': channel, 'name': channel, 'value': None, 'maintenance_locked': False}
        for channel in management._rcm_channel_ids()
    ]
    channels[0]['value'] = True
    channels[0]['maintenance_locked'] = True

    config = management.rcm_config_from_channels(channels)

    assert len(config['channels']) == 32
    assert config['channels'][0] == {'channel': 'A1', 'name': 'A1', 'on': True, 'lockout': True}
    assert config['channels'][1]['on'] is False


def test_lcm_config_from_channels_uses_correct_8_10_4_schema():
    channels = []
    for channel in management._lcm_channel_ids():
        channels.append({
            'channel': channel,
            'name': channel,
            'type_label': 'Relay' if channel.startswith('A') else '0-10V' if channel.startswith('10-') else '110V',
            'maintenance_locked': channel == 'HV-4',
            'emergency_lighting': channel == 'A1',
            'max_intensity': 80,
            'fade_seconds': 2.5,
        })

    config = management.lcm_config_from_channels(channels)

    assert len(config['channels']) == 22
    assert config['channels'][0]['channel'] == 'A1'
    assert config['channels'][8]['channel'] == '10-1'
    assert config['channels'][17]['channel'] == '10-10'
    assert config['channels'][18]['channel'] == 'HV-1'
    assert config['channels'][-1]['lockout'] is True


def test_conflict_supervisor_status_reports_healthy_recent_ack(monkeypatch):
    monkeypatch.setattr(management.settings, 'hcm_heartbeat_device_id', '48b02d87db16')
    monkeypatch.setattr(management.settings, 'conflict_heartbeat_timeout_s', 15)

    result = management._conflict_supervisor_from_status({
        'device_id': '3c53bbf7adb2',
        'hostname': 'conflict',
        'health': {'state': 'healthy'},
        'status': {
            'state': 'operational',
            'registry': {
                '48b02d87db16': {
                    'hostname': 'jetson',
                    'online': True,
                    'last_seen_seconds_ago': 4,
                    'last_sequence': 100,
                    'health': {'state': 'healthy'},
                    'status': {'state': 'operational'},
                    'active_fault': None,
                }
            },
        },
    })

    assert result['status'] == 'Healthy'
    assert result['last_ack_age_seconds'] == 4
    assert result['hcm_device_id'] == '48b02d87db16'


def test_conflict_supervisor_status_distinguishes_stale_unknown_and_offline(monkeypatch):
    monkeypatch.setattr(management.settings, 'hcm_heartbeat_device_id', '48b02d87db16')
    monkeypatch.setattr(management.settings, 'conflict_heartbeat_timeout_s', 15)
    base = {
        'health': {'state': 'healthy'},
        'status': {'state': 'operational', 'registry': {}},
    }

    missing = management._conflict_supervisor_from_status(base)
    assert missing['status'] == 'Unknown'

    stale_payload = {
        **base,
        'status': {
            'state': 'operational',
            'registry': {'48b02d87db16': {'online': True, 'last_seen_seconds_ago': 22}},
        },
    }
    stale = management._conflict_supervisor_from_status(stale_payload)
    assert stale['status'] == 'Degraded'

    offline_payload = {
        **base,
        'status': {
            'state': 'operational',
            'registry': {'48b02d87db16': {'online': False, 'last_seen_seconds_ago': 90}},
        },
    }
    offline = management._conflict_supervisor_from_status(offline_payload)
    assert offline['status'] == 'Offline'


def test_sim_physical_ai_inventory_and_supported_rmc_binding_channels():
    capabilities = {'hexa-aio', 'rmc-can'}

    assert management._sim_analog_channels() == [f'AI-{i}' for i in range(1, 11)]
    assert management._module_supports_channel('SIM', 'AI-10', capabilities) is True
    assert management._module_supports_channel('SIM', 'AI-11', capabilities) is False
    assert management._module_supports_channel('SIM', 'RMC:CAN0:1', capabilities) is True


@pytest.mark.asyncio
async def test_create_logical_device_records_audit_event(monkeypatch):
    conn = FakeManagementConn()
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.create_logical_device(
        logical_name='Kitchen Light',
        device_class='light',
        metadata={'emergency_lighting': False},
        actor='patrick',
    )

    assert result['logical_name'] == 'Kitchen Light'
    assert result['device_class'] == 'light'
    assert len(conn.audit_events) == 1
    assert conn.audit_events[0][0:4] == ('patrick', 'logical_device.create', 'logical_device', '1')
    assert conn.transaction_depth == 0


@pytest.mark.asyncio
async def test_create_binding_uses_logical_name_and_module_identifier_without_actuation(monkeypatch):
    conn = FakeManagementConn()
    conn.logical_devices['Kitchen Light'] = {
        'id': 1,
        'logical_name': 'Kitchen Light',
        'room_id': None,
        'room': None,
        'device_class': 'light',
        'enabled': True,
        'maintenance_locked': False,
        'metadata': {},
    }
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.create_binding(
        logical_name='Kitchen Light',
        module_identifier='48:b0:2d:87:db:16',
        channel='10-1',
        binding_type='primary',
        actor='patrick',
    )

    assert result['logical_name'] == 'Kitchen Light'
    assert result['module_hostname'] == 'LCM01'
    assert result['module_device_id'] == '48b02d87db16'
    assert result['channel'] == '10-1'
    assert conn.audit_events[-1][1] == 'binding.create'


@pytest.mark.asyncio
async def test_binding_rejects_unsupported_channel_before_insert(monkeypatch):
    conn = FakeManagementConn()
    conn.logical_devices['Kitchen Light'] = {
        'id': 1,
        'logical_name': 'Kitchen Light',
        'room_id': None,
        'room': None,
        'device_class': 'light',
        'enabled': True,
        'maintenance_locked': False,
        'metadata': {},
    }
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    with pytest.raises(management.ValidationError):
        await management.create_binding(
            logical_name='Kitchen Light',
            module_identifier='LCM01',
            channel='D9',
            binding_type='primary',
            actor='patrick',
        )

    assert conn.bindings == {}
    assert conn.audit_events == []


@pytest.mark.asyncio
async def test_binding_rejects_conflicting_active_assignment(monkeypatch):
    conn = FakeManagementConn()
    conn.logical_devices['Kitchen Light'] = {
        'id': 1,
        'logical_name': 'Kitchen Light',
        'room_id': None,
        'room': None,
        'device_class': 'light',
        'enabled': True,
        'maintenance_locked': False,
        'metadata': {},
    }
    conn.logical_devices['Hall Light'] = {
        'id': 2,
        'logical_name': 'Hall Light',
        'room_id': None,
        'room': None,
        'device_class': 'light',
        'enabled': True,
        'maintenance_locked': False,
        'metadata': {},
    }
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    await management.create_binding(
        logical_name='Kitchen Light',
        module_identifier='LCM01',
        channel='10-1',
        binding_type='primary',
        actor='patrick',
    )
    with pytest.raises(management.ValidationError):
        await management.create_binding(
            logical_name='Hall Light',
            module_identifier='LCM01',
            channel='10-1',
            binding_type='primary',
            actor='patrick',
        )

    assert len(conn.bindings) == 1


@pytest.mark.asyncio
async def test_logical_device_room_update_can_explicitly_clear_room(monkeypatch):
    conn = FakeManagementConn()
    conn.logical_devices['Kitchen Light'] = {
        'id': 1,
        'logical_name': 'Kitchen Light',
        'room_id': 7,
        'room': None,
        'device_class': 'light',
        'enabled': True,
        'maintenance_locked': False,
        'metadata': {},
    }
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.update_logical_device(
        'Kitchen Light',
        actor='patrick',
        room_id=None,
    )

    assert result['room_id'] is None


@pytest.mark.asyncio
async def test_logical_device_write_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await api.logical_device_create(
            api.LogicalDeviceCreateIn(logical_name='Kitchen Light', device_class='light'),
            {'user': 'viewer', 'role': 'READONLY'},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_logical_device_create_api_calls_management(monkeypatch):
    async def create_logical_device(**kwargs):
        assert kwargs['actor'] == 'patrick'
        assert kwargs['logical_name'] == 'Kitchen Light'
        return {'id': 1, 'logical_name': 'Kitchen Light'}

    monkeypatch.setattr(api.management, 'create_logical_device', create_logical_device)

    result = await api.logical_device_create(
        api.LogicalDeviceCreateIn(logical_name='Kitchen Light', device_class='light'),
        {'user': 'patrick', 'role': 'ADMIN'},
    )

    assert result == {'id': 1, 'logical_name': 'Kitchen Light'}


class FakeDeviceAdminConn:
    def __init__(self):
        self.audit_events = []
        self.transaction_depth = 0
        self.module = {
            'id': 7,
            'device_id': '2ccf675d3414',
            'module_uuid': None,
            'identity_interface': 'eth0',
            'module_type': 'RCM',
            'hostname': 'LAB1',
            'ip_address': '192.168.20.36',
            'heartbeat_ip': None,
            'online': True,
            'control_session_online': True,
            'supervision_state': 'unknown',
            'supervision_last_seen': None,
            'supervision_fresh_until': None,
            'last_health': {},
            'hardware_revision': None,
            'software_version': '0.1.0',
            'config_version': 1,
            'last_seen': None,
            'last_state': {
                'state': {
                    'lab_role': 'UNASSIGNED',
                    'simulation': True,
                    'physical_outputs_enabled': False,
                    'relays': {'A1': {'on': False}},
                }
            },
            'commissioned_at': None,
        }
        self.capabilities = [{'capability': 'relay-32', 'details': {}, 'first_seen_at': None, 'updated_at': None}]
        self.logical = {
            'id': 22,
            'logical_name': 'RCM2 Channel 1',
            'room_id': None,
            'room': None,
            'device_class': 'relay',
            'enabled': True,
            'maintenance_locked': False,
            'metadata': {'channel_name': 'Pump Enable'},
        }
        self.binding = {
            'binding_id': 33,
            'channel': 'A1',
            'binding_enabled': True,
            'logical_device_id': 22,
            'logical_name': 'RCM2 Channel 1',
            'logical_enabled': True,
            'maintenance_locked': False,
            'logical_metadata': {'channel_name': 'Pump Enable'},
        }

    def transaction(self):
        return FakeTransaction(self)

    async def fetchrow(self, query, *args):
        if 'SELECT *' in query and 'FROM modules' in query:
            identifier, device_id = args
            if identifier in {'LAB1', '7'} or device_id == self.module['device_id']:
                return self.module
            return None
        if 'SELECT d.*, NULL::text AS room' in query:
            module_id, channel = args
            if module_id == self.module['id'] and channel == self.binding['channel']:
                return {**self.logical, 'room': None}
            return None
        if 'UPDATE logical_devices' in query and 'jsonb_set' in query:
            _, name = args
            self.logical['metadata'] = {'channel_name': name}
            self.binding['logical_metadata'] = {'channel_name': name}
            return {**self.logical, 'room': None}
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def fetch(self, query, *args):
        if 'FROM module_capabilities' in query:
            return self.capabilities
        if 'FROM device_bindings b' in query and 'JOIN logical_devices d' in query:
            module_id, channels = args
            if module_id == self.module['id'] and self.binding['channel'] in channels:
                return [self.binding]
            return []
        raise AssertionError(f'unexpected fetch: {query}')

    async def execute(self, query, *args):
        if 'INSERT INTO device_management_events' in query:
            self.audit_events.append(args)
            return
        raise AssertionError(f'unexpected execute: {query}')


@pytest.mark.asyncio
async def test_device_admin_uses_reported_lab1_role_not_hostname(monkeypatch):
    conn = FakeDeviceAdminConn()
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.get_device_admin('LAB1')

    assert result['module']['hostname'] == 'LAB1'
    assert result['module']['device_id'] == '2ccf675d3414'
    assert result['effective_role'] == 'UNASSIGNED'
    assert result['simulation'] is True
    assert result['physical_outputs_enabled'] is False


@pytest.mark.asyncio
async def test_rcm_channels_use_real_bindings_and_disable_inhibited_outputs(monkeypatch):
    conn = FakeDeviceAdminConn()
    conn.module['last_state']['state']['lab_role'] = 'RCM'
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.get_rcm_channels('LAB1')
    first = result['channels'][0]
    second = result['channels'][1]

    assert len(result['channels']) == 32
    assert first['channel'] == 'A1'
    assert first['logical_name'] == 'RCM2 Channel 1'
    assert first['name'] == 'Pump Enable'
    assert first['value'] is False
    assert first['control_enabled'] is False
    assert first['disabled_reason'] == 'Physical outputs disabled'
    assert second['bound'] is False
    assert second['disabled_reason'] == 'No logical binding'


@pytest.mark.asyncio
async def test_rcm_channel_name_update_persists_metadata_without_renaming_logical(monkeypatch):
    conn = FakeDeviceAdminConn()
    conn.module['last_state']['state']['lab_role'] = 'RCM'
    monkeypatch.setattr(management.db, 'acquire', lambda: FakeAcquire(conn))

    result = await management.update_rcm_channel_name('LAB1', 'A1', name='Well Pump', actor='patrick')

    assert conn.logical['logical_name'] == 'RCM2 Channel 1'
    assert conn.logical['metadata']['channel_name'] == 'Well Pump'
    assert result['channels'][0]['name'] == 'Well Pump'
    assert conn.audit_events[-1][1] == 'rcm_channel.name_update'


@pytest.mark.asyncio
async def test_rcm_channel_name_api_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await api.device_admin_rcm_channel_name(
            'LAB1',
            'A1',
            api.RcmChannelNameIn(name='Well Pump'),
            {'user': 'viewer', 'role': 'READONLY'},
        )

    assert exc.value.status_code == 403
