import sys
from pathlib import Path
from importlib import import_module
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from types import SimpleNamespace
hvac = import_module('01_HCM.hvac')
hcm_db = import_module('01_HCM.db')
HVACController = hvac.HVACController
RoomReading = hvac.RoomReading
Mode = hvac.Mode


def controller(events):
    async def out(n, v):
        events.append((n, v))

    async def damper(r, v):
        events.append((r.room, v))

    h = HVACController(out, damper)
    h.DAMPER_LEAD_S = 0
    h.FAN_LEAD_S = 0
    return h


def hvac_globals(**overrides):
    values = dict(
        HVAC_Deadband_F=2.0,
        HVAC_Damper_Lead=25,
        HVAC_Fan_Lead=35,
        HVAC_Fan_Postrun=4000,
        HVAC_Cool_Min_Run=5000,
        HVAC_Heat_Min_Run=6000,
        HVAC_Cool_Restart_Lockout=7000,
        HVAC_Heat_Restart_Lockout=8000,
        HVAC_Default_Setpoint_F=67.0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeHVACConn:
    def __init__(self):
        self.executed = []

    async def execute(self, *args):
        self.executed.append(args)

@pytest.mark.asyncio
async def test_cool_sequence(monkeypatch):
    events=[]
    h=controller(events)
    h.COOL_RESTART_LOCKOUT_S=0
    h.state.mode=Mode.COOL; h.state.setpoint_f=70
    h.rooms['Office']=RoomReading('Office',74,True,False)
    h.rooms['Kitchen']=RoomReading('Kitchen',74,True,True,'Kitchen Damper')
    await h.evaluate()
    assert ('FAN',True) in events and ('COOL',True) in events


@pytest.mark.asyncio
async def test_off_opens_hvac_calls_immediately():
    events = []
    h = controller(events)
    h.state.mode = Mode.OFF
    h.state.fan = True
    h.state.cool = True
    h.state.heat = True
    h.state.call_started_at = 1
    h.state.postrun_until = 999
    h.rooms['Office'] = RoomReading('Office', 74, True)

    await h.evaluate()

    assert ('COOL', False) in events
    assert ('HEAT', False) in events
    assert ('FAN', False) in events
    assert h.state.call_started_at is None
    assert h.state.postrun_until == 0


@pytest.mark.asyncio
async def test_force_off_reasserts_all_outputs_when_cached_state_is_false():
    events = []
    h = controller(events)
    await h.force_off()
    assert events == [('COOL', False), ('HEAT', False), ('FAN', False)]


@pytest.mark.asyncio
async def test_force_off_attempts_all_outputs_after_an_early_failure():
    events = []

    async def out(name, value):
        events.append((name, value))
        if name == 'COOL':
            raise RuntimeError('cool relay unavailable')

    h = HVACController(out, controller([]).damper)
    result = await h.force_off()
    assert events == [('COOL', False), ('HEAT', False), ('FAN', False)]
    assert result['ok'] is False
    assert result['failures'][0]['output'] == 'COOL'


@pytest.mark.asyncio
async def test_fan_mode_runs_until_changed_even_without_occupied_rooms():
    events = []
    h = controller(events)
    h.state.mode = Mode.FAN
    h.rooms['Office'] = RoomReading('Office', 70, False)

    await h.evaluate()

    assert ('FAN', True) in events
    assert h.state.fan is True


@pytest.mark.asyncio
async def test_cool_minimum_run_prevents_early_stop(monkeypatch):
    events = []
    h = controller(events)
    h.state.mode = Mode.COOL
    h.state.setpoint_f = 70
    h.state.cool = True
    h.state.fan = True
    h.state.call_started_at = 100
    h.rooms['Office'] = RoomReading('Office', 69, True, False)
    monkeypatch.setattr(hvac.time, 'monotonic', lambda: 150)

    await h.evaluate()

    assert ('COOL', False) not in events
    assert h.state.cool is True


@pytest.mark.asyncio
async def test_cool_stops_after_minimum_run_and_keeps_fan_postrun(monkeypatch):
    events = []
    h = controller(events)
    h.state.mode = Mode.COOL
    h.state.setpoint_f = 70
    h.state.cool = True
    h.state.fan = True
    h.state.call_started_at = 100
    h.rooms['Office'] = RoomReading('Office', 69, True, False)
    monkeypatch.setattr(hvac.time, 'monotonic', lambda: 230)

    await h.evaluate()

    assert ('COOL', False) in events
    assert ('FAN', False) not in events
    assert h.state.cool is False
    assert h.state.fan is True
    assert h.state.postrun_until == 290


@pytest.mark.asyncio
async def test_cool_restart_lockout_blocks_short_cycle(monkeypatch):
    events = []
    h = controller(events)
    h.state.mode = Mode.COOL
    h.state.setpoint_f = 70
    h.state.last_cool_off = 100
    h.rooms['Office'] = RoomReading('Office', 74, True, False)
    monkeypatch.setattr(hvac.time, 'monotonic', lambda: 200)

    await h.evaluate()

    assert ('COOL', True) not in events
    assert h.state.cool is False


@pytest.mark.asyncio
async def test_failed_room_sensor_damper_defaults_open():
    events = []
    h = controller(events)
    h.RESTART_LOCKOUT_S = 0
    h.state.mode = Mode.HEAT
    h.state.setpoint_f = 70
    h.rooms['Office'] = RoomReading('Office', 60, True, True, 'Office Damper', sensor_ok=False)

    await h.evaluate()

    assert ('Office', True) in events


@pytest.mark.asyncio
async def test_hvac_state_persists_mode_and_setpoint(monkeypatch):
    events = []
    conn = FakeHVACConn()
    h = controller(events)
    h.state.mode = Mode.HEAT
    h.state.setpoint_f = 68
    monkeypatch.setattr(hcm_db, 'acquire', lambda: FakeAcquire(conn))

    await h.persist_state()

    assert conn.executed[0][1:] == ('HEAT', 68)


def test_hvac_uses_global_configured_defaults_and_ms_timings():
    events = []
    h = HVACController(lambda n, v: None, lambda r, v: None, globals_=hvac_globals())

    assert h.state.setpoint_f == 67.0
    assert h.DEADBAND_F == 2.0
    assert h.DAMPER_LEAD_S == 0.025
    assert h.FAN_LEAD_S == 0.035
    assert h.FAN_POSTRUN_S == 4.0
    assert h.COOL_RESTART_LOCKOUT_S == 7.0
    assert h.HEAT_RESTART_LOCKOUT_S == 8.0
