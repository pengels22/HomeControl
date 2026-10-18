from importlib import import_module

import pytest

devices = import_module('01_HCM.devices')
priority = import_module('01_HCM.priority')


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePriorityConn:
    def __init__(self):
        self.intents = {}
        self.maintenance_locked = False

    async def fetchrow(self, query, *args):
        if 'FROM logical_devices d' in query and 'WHERE d.logical_name=$1' in query:
            return {
                'logical_device_id': 42,
                'logical_name': args[0],
                'hostname': 'LCM01',
                'maintenance_locked': self.maintenance_locked,
                'channel': 'A1',
                'binding_type': 'primary',
                'metadata': {},
            }
        if 'FROM logical_devices d' in query and 'WHERE d.id=$1' in query:
            return {
                'logical_name': 'Kitchen Light',
                'hostname': 'LCM01',
                'maintenance_locked': self.maintenance_locked,
                'channel': 'A1',
                'metadata': {},
            }
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def fetch(self, query, *args):
        if 'FROM logical_devices d' in query and 'WHERE d.logical_name=$1' in query:
            return [await self.fetchrow(query, *args)]
        if 'FROM output_intents' in query:
            rows = []
            for source, command in self.intents.get(args[0], {}).items():
                rows.append({'logical_device_id': args[0], 'source': source, 'command': command})
            return rows
        raise AssertionError(f'unexpected fetch: {query}')

    async def execute(self, query, *args):
        if 'INSERT INTO output_intents' in query:
            logical_device_id, source, command = args
            self.intents.setdefault(logical_device_id, {})[source] = command
            return
        if 'INSERT INTO output_arbitration_events' in query:
            return
        raise AssertionError(f'unexpected execute: {query}')


@pytest.mark.asyncio
async def test_local_override_suppresses_user_command(monkeypatch):
    conn = FakePriorityConn()
    sent = []
    monkeypatch.setattr(devices.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(priority.db, 'acquire', lambda: FakeAcquire(conn))

    async def command_by_hostname(hostname, payload):
        sent.append((hostname, payload))
        return {'ok': True}

    monkeypatch.setattr(devices.registry, 'command_by_hostname', command_by_hostname)

    await devices.command_logical(
        'Kitchen Light',
        {'op': 'set_relay', 'value': True},
        source=priority.OutputSource.LOCAL_OVERRIDE,
    )
    result = await devices.command_logical(
        'Kitchen Light',
        {'op': 'set_relay', 'value': False},
        source=priority.OutputSource.USER,
    )

    assert result['suppressed'] is True
    assert result['active_source'] == 'local_override'
    assert sent == [('LCM01', {'op': 'set_relay', 'value': True, 'channel': 'A1'})]


@pytest.mark.asyncio
async def test_maintenance_lockout_sends_deenergized_effective_command(monkeypatch):
    conn = FakePriorityConn()
    conn.maintenance_locked = True
    sent = []
    monkeypatch.setattr(devices.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(priority.db, 'acquire', lambda: FakeAcquire(conn))

    async def command_by_hostname(hostname, payload):
        sent.append((hostname, payload))
        return {'ok': True}

    monkeypatch.setattr(devices.registry, 'command_by_hostname', command_by_hostname)

    result = await devices.command_logical('Kitchen Light', {'op': 'set_relay', 'value': True})

    assert result['suppressed'] is True
    assert result['arbitration']['reason'] == 'maintenance_lockout'
    assert sent == [('LCM01', {'op': 'set_relay', 'value': False, 'channel': 'A1'})]
    assert conn.intents == {}


@pytest.mark.asyncio
async def test_scene_and_schedule_cannot_bypass_maintenance_lockout(monkeypatch):
    conn = FakePriorityConn()
    conn.maintenance_locked = True
    sent = []
    monkeypatch.setattr(devices.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(priority.db, 'acquire', lambda: FakeAcquire(conn))

    async def command_by_hostname(hostname, payload):
        sent.append(payload)
        return {'ok': True}

    monkeypatch.setattr(devices.registry, 'command_by_hostname', command_by_hostname)

    scene = await devices.command_logical('Kitchen Light', {'op': 'set_relay', 'value': True}, source=priority.OutputSource.SCENE)
    scheduled = await devices.command_logical('Kitchen Light', {'op': 'set_relay', 'value': True}, source=priority.OutputSource.SCHEDULE)

    assert scene['arbitration']['effective_state']['energized'] is False
    assert scheduled['arbitration']['effective_state']['energized'] is False
    assert all(payload['value'] is False for payload in sent)


@pytest.mark.asyncio
async def test_lockout_clear_does_not_replay_stale_request(monkeypatch):
    conn = FakePriorityConn()
    conn.maintenance_locked = True
    sent = []
    monkeypatch.setattr(devices.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(priority.db, 'acquire', lambda: FakeAcquire(conn))

    async def command_by_hostname(hostname, payload):
        sent.append(payload)
        return {'ok': True}

    monkeypatch.setattr(devices.registry, 'command_by_hostname', command_by_hostname)

    await devices.command_logical('Kitchen Light', {'op': 'set_relay', 'value': True})
    conn.maintenance_locked = False
    result = await devices.apply_active_intent(42)

    assert result['idle'] is True
    assert sent == [{'op': 'set_relay', 'value': False, 'channel': 'A1'}]
