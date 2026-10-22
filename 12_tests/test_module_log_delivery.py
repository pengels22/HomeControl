from importlib import import_module

import pytest


agent_mod = import_module('08_servises.common.agent')
rcm_mod = import_module('04_RCM.main')
lcm_mod = import_module('03_LCM.main')


class FakeWriter:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


@pytest.mark.asyncio
async def test_log_ack_removes_events_without_terminating_session(tmp_path, monkeypatch):
    agent = agent_mod.ModuleAgent('RCM', {
        'identity_path': str(tmp_path / 'identity.json'),
        'hcm_host': '127.0.0.1',
        'hcm_port': 6501,
        'heartbeat_seconds': 60,
    })
    agent.event_queue.enqueue({'event_id': 'evt-1', 'message': 'queued'})
    writer = FakeWriter()
    messages = iter([
        {'type': 'ready', 'payload': {}},
        {'type': 'log_ack', 'payload': {'event_ids': ['evt-1']}},
    ])
    sent = []

    async def open_connection(*args, **kwargs):
        return object(), writer

    async def read_frame(_reader):
        try:
            return next(messages)
        except StopIteration:
            raise ConnectionError('test session end')

    async def write_frame(_writer, message):
        sent.append(message)
        return None

    monkeypatch.setattr(agent_mod.asyncio, 'open_connection', open_connection)
    monkeypatch.setattr(agent_mod, 'read_frame', read_frame)
    monkeypatch.setattr(agent_mod, 'write_frame', write_frame)
    monkeypatch.setattr(agent, 'heartbeat_status', _noop)
    monkeypatch.setattr(agent, 'heartbeat_fault', _noop)
    agent.running = True
    with pytest.raises(ConnectionError):
        await agent._session()
    assert agent.event_queue.count() == 0
    assert agent.hcm_connected is False
    assert writer.closed is True
    assert any(message['type'] == 'state' for message in sent)


async def _noop(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_hcm_disconnect_holds_module_outputs_and_rcm_local_override_still_works(tmp_path, monkeypatch):
    config = {
        'identity_path': str(tmp_path / 'identity.json'),
        'runtime_root': str(tmp_path / 'runtime'),
        'io_mode': 'simulated',
        'mock_hardware': True,
        'heartbeat_seconds': 60,
    }
    rcm = rcm_mod.RCMAgent(config)
    lcm = lcm_mod.LCMAgent({**config, 'identity_path': str(tmp_path / 'lcm-identity.json')})
    rcm.relays.set('A1', True)
    lcm.relays.set('A1', True)
    lcm.lv_dimmers.set_percent('10-1', 60)
    sent = []
    reads = [0]

    async def open_connection(*_args, **_kwargs):
        return object(), FakeWriter()

    async def read_frame(_reader):
        reads[0] += 1
        if reads[0] == 1:
            return {'type': 'ready', 'payload': {}}
        raise ConnectionError('HCM stopped')

    async def write_frame(_writer, message):
        sent.append(message)

    monkeypatch.setattr(agent_mod.asyncio, 'open_connection', open_connection)
    monkeypatch.setattr(agent_mod, 'read_frame', read_frame)
    monkeypatch.setattr(agent_mod, 'write_frame', write_frame)
    for module in (rcm, lcm):
        sent.clear()
        reads[0] = 0
        monkeypatch.setattr(module, 'heartbeat_status', _noop)
        monkeypatch.setattr(module, 'heartbeat_fault', _noop)
        with pytest.raises(ConnectionError):
            await module._session()
        assert module.hcm_connected is False
        assert any(message['type'] == 'state' for message in sent)

    assert rcm.relays.get('A1') is True
    assert lcm.relays.get('A1') is True
    assert lcm.lv_dimmers.snapshot()['10-1']['percent'] == 60
    result = await rcm.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': False, 'source': 'local_override'})
    assert result['ok'] is True
    assert rcm.relays.get('A1') is False
    assert lcm.relays.get('A1') is True
    sent.clear()
    reads[0] = 0
    with pytest.raises(ConnectionError):
        await rcm._session()
    snapshot = next(message for message in sent if message['type'] == 'state')
    assert snapshot['payload']['state']['relays']['A1'] is False


@pytest.mark.asyncio
async def test_disconnect_during_identify_clears_connection_status(tmp_path, monkeypatch):
    agent = agent_mod.ModuleAgent('RCM', {'identity_path': str(tmp_path / 'identity.json')})
    writer = FakeWriter()

    async def open_connection(*_args, **_kwargs):
        return object(), writer

    async def read_frame(_reader):
        raise ConnectionError('HCM stopped before identify reply')

    async def write_frame(_writer, _message):
        return None

    monkeypatch.setattr(agent_mod.asyncio, 'open_connection', open_connection)
    monkeypatch.setattr(agent_mod, 'read_frame', read_frame)
    monkeypatch.setattr(agent_mod, 'write_frame', write_frame)
    monkeypatch.setattr(agent, 'heartbeat_status', _noop)
    monkeypatch.setattr(agent, 'heartbeat_fault', _noop)
    with pytest.raises(ConnectionError):
        await agent._session()
    assert agent.hcm_connected is False
    assert writer.closed is True
