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

    async def fetchrow(self, query, *args):
        if 'FROM logical_devices d' in query and 'WHERE d.logical_name=$1' in query:
            return {
                'logical_device_id': 42,
                'hostname': 'LCM01',
                'maintenance_locked': False,
                'channel': 'A1',
                'binding_type': 'primary',
                'metadata': {},
            }
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def fetch(self, query, *args):
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
