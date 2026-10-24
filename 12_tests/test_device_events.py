from importlib import import_module

import pytest

events = import_module('02_HCM.device_events')
automation = import_module('02_HCM.automation')


def test_normalized_event_is_bounded_and_provider_neutral():
    event = events.normalize_device_event(device_ref='device-1', category='button', action='press', subtype='button_1', metadata={'raw': {'deep': {'x': {'y': 1}}}})
    assert event['category'] == 'button' and event['action'] == 'press'
    assert event['metadata']['raw']['deep']['x']['y'] == '[TRUNCATED]'


def test_device_event_trigger_filters_device_action_and_subtype():
    engine = automation.AutomationEngine(None)
    trigger = {'type': 'device_event', 'device_ref': 'd1', 'category': 'button', 'action': 'press', 'subtype': 'button_1'}
    event = {'event_type': 'hcm_native.device_event', 'event_id': 1, 'payload': {'device_ref': 'd1', 'category': 'button', 'action': 'press', 'subtype': 'button_1'}}
    assert engine._trigger_matches(trigger, event)
    assert not engine._trigger_matches(trigger, {**event, 'payload': {**event['payload'], 'action': 'hold'}})


@pytest.mark.asyncio
async def test_runtime_deduplicates_only_same_provider_event_identity():
    class Context:
        def __init__(self): self.calls = []
        async def emit(self, name, payload): self.calls.append((name, payload)); return payload
    class Registry:
        def __init__(self): self.context_obj = Context()
        def context(self, name): return self.context_obj
    runtime = events.DeviceEventRuntime(Registry())
    event = events.normalize_device_event(device_ref='d1', category='button', action='press')
    assert await runtime.emit(event, provider_id='zha', source_event_id='1')
    assert await runtime.emit(event, provider_id='zha', source_event_id='1') is None
    assert await runtime.emit(event, provider_id='zha', source_event_id='2')
    assert len(runtime.registry.context_obj.calls) == 2
