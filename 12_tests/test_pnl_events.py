from importlib import import_module

import pytest


events = import_module('02_HCM.pnl_events')


def test_event_limits_are_bounded():
    assert events.MAX_REPLAY_EVENTS == 100


async def test_publish_state_event_is_ordered_and_bounded():
    class Conn:
        def __init__(self): self.calls = []
        async def fetchval(self, *_args): self.calls.append(('sequence', _args)); return 4
        async def execute(self, *_args): self.calls.append(('insert', _args))
    conn = Conn()
    assert await events.publish_state_event(conn, '020000000010', 'state', {'state': 'ON'}) == 4
    assert conn.calls[-1][0] == 'insert'
    with pytest.raises(ValueError):
        await events.publish_state_event(conn, '020000000010', 'state', {'value': 'x' * events.MAX_EVENT_PAYLOAD})
