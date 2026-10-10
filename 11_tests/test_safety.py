from importlib import import_module

import pytest

safety_mod = import_module('01_HCM.safety')
SafetyController = safety_mod.SafetyController


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self):
        self.executed = []
        self.fetches = []

    async def execute(self, *args):
        self.executed.append(args)

    async def fetch(self, query):
        self.fetches.append(query)
        return [{'logical_name': 'Kitchen Light'}, {'logical_name': 'Hall Light'}]


class FakeHVAC:
    def __init__(self):
        self.force_off_count = 0

    async def force_off(self):
        self.force_off_count += 1


@pytest.mark.asyncio
async def test_fire_forces_hvac_off_and_commands_only_available_lights(monkeypatch):
    conn = FakeConn()
    hvac = FakeHVAC()
    sent = []
    commands = []

    monkeypatch.setattr(safety_mod.db, 'acquire', lambda: FakeAcquire(conn))

    async def send(n):
        sent.append(n)

    monkeypatch.setattr(safety_mod.notifications, 'send', send)

    async def command_logical(logical_name, command, source='user', safety_conditions=None):
        commands.append((logical_name, command, source, safety_conditions))
        return {'ok': True}

    monkeypatch.setattr(safety_mod, 'command_logical', command_logical)

    controller = SafetyController(hvac)
    await controller.set_fire(True)

    assert controller.fire_active is True
    assert hvac.force_off_count == 1
    assert sent[0].priority == 'critical'
    assert commands == [
        ('Kitchen Light', {'op': 'light', 'percent': 100, 'value': True}, safety_mod.OutputSource.LIFE_SAFETY, {'fire_active'}),
        ('Hall Light', {'op': 'light', 'percent': 100, 'value': True}, safety_mod.OutputSource.LIFE_SAFETY, {'fire_active'}),
    ]
    assert "metadata->>'emergency_lighting'" in conn.fetches[0]
    assert conn.executed[0][1:3] == ('fire', True)


@pytest.mark.asyncio
async def test_repeated_fire_state_is_idempotent(monkeypatch):
    conn = FakeConn()
    hvac = FakeHVAC()
    commands = []

    monkeypatch.setattr(safety_mod.db, 'acquire', lambda: FakeAcquire(conn))

    async def send(n):
        return None

    monkeypatch.setattr(safety_mod.notifications, 'send', send)

    async def command_logical(logical_name, command, source='user', safety_conditions=None):
        commands.append((logical_name, command))
        return {'ok': True}

    monkeypatch.setattr(safety_mod, 'command_logical', command_logical)

    controller = SafetyController(hvac)
    await controller.set_fire(True)
    await controller.set_fire(True)

    assert hvac.force_off_count == 1
    assert len(conn.executed) == 1
    assert len(commands) == 2


@pytest.mark.asyncio
async def test_fire_detection_logs_but_does_not_command_lights_during_lockout(monkeypatch):
    conn = FakeConn()
    hvac = FakeHVAC()
    commands = []
    reports = []

    monkeypatch.setattr(safety_mod.db, 'acquire', lambda: FakeAcquire(conn))

    async def send(n):
        return None

    monkeypatch.setattr(safety_mod.notifications, 'send', send)

    async def command_logical(logical_name, command, source='user', safety_conditions=None):
        commands.append((logical_name, command))
        return {'ok': True}

    monkeypatch.setattr(safety_mod, 'command_logical', command_logical)

    class Reporter:
        async def status(self, name, value):
            reports.append(('status', name, value))

        async def fault(self, name, detail):
            reports.append(('fault', name, detail))

    controller = SafetyController(hvac, heartbeat=Reporter())
    await controller.set_maintenance_lockout(True)
    await controller.set_fire(True)

    assert controller.fire_active is True
    assert hvac.force_off_count == 1
    assert conn.executed[0][1:3] == ('fire', True)
    assert commands == []
    assert ('fault', 'output_command_inhibited', 'fire emergency lighting inhibited by maintenance lockout') in reports
