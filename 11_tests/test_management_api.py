from importlib import import_module
import json

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

    async def fetch(self, query, *args):
        if 'FROM modules' in query:
            return list(self.modules.values())
        if 'FROM module_capabilities' in query:
            return []
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
                'room_id': args[3] if args[3] is not None else current['room_id'],
                'enabled': args[4] if args[4] is not None else current['enabled'],
                'maintenance_locked': args[5] if args[5] is not None else current['maintenance_locked'],
                'metadata': json.loads(args[6]) if args[6] is not None else current['metadata'],
            })
            self.logical_devices[logical_name] = current
            return current
        if 'SELECT id' in query and 'FROM modules' in query:
            text, device_id = args
            for row in self.modules.values():
                if str(row['id']) == text or row['hostname'] == text or row['device_id'] == device_id:
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
