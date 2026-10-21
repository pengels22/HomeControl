from importlib import import_module

import pytest


agent_mod = import_module('08_servises.common.agent')


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

    async def open_connection(*args, **kwargs):
        return object(), writer

    async def read_frame(_reader):
        try:
            return next(messages)
        except StopIteration:
            raise ConnectionError('test session end')

    async def write_frame(_writer, message):
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


async def _noop(*args, **kwargs):
    return None
