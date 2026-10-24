import asyncio
from importlib import import_module

import pytest

zones = import_module('02_HCM.zones')


def test_distance_uses_geographic_meters():
    assert zones.distance_m(0, 0, 0, 0) == 0
    assert 110_000 < zones.distance_m(0, 0, 1, 0) < 112_500


@pytest.mark.asyncio
async def test_zone_enter_leave_initial_and_no_duplicates():
    events = []
    evaluator = zones.ZoneEvaluator([{'zone_id': 'z', 'enabled': True, 'latitude': 0, 'longitude': 0, 'radius_m': 100}], event_sink=events.append)
    assert await evaluator.update('tracker', 0, 0) == []
    assert (await evaluator.update('tracker', 0.002, 0))[0]['event'] == 'leave'
    assert (await evaluator.update('tracker', 0, 0))[0]['event'] == 'enter'
    assert await evaluator.update('tracker', 0.0015, 0)
    assert [event['event'] for event in events] == ['leave', 'enter', 'leave']


@pytest.mark.asyncio
async def test_zone_unavailable_and_overlapping_membership_are_independent():
    events = []
    evaluator = zones.ZoneEvaluator([
        {'zone_id': 'a', 'enabled': True, 'latitude': 0, 'longitude': 0, 'radius_m': 100},
        {'zone_id': 'b', 'enabled': True, 'latitude': 0, 'longitude': 0, 'radius_m': 200},
    ], event_sink=events.append)
    await evaluator.update('tracker', 0, 0)
    assert await evaluator.update('tracker', None, None, available=False) == []
    assert evaluator.is_member('tracker', 'a') is True
    await evaluator.update('tracker', 0.002, 0)
    assert {event['zone_ref'] for event in events} == {'a', 'b'}


def test_disabled_zone_does_not_emit_synthetic_leave():
    evaluator = zones.ZoneEvaluator([{'zone_id': 'z', 'enabled': True, 'latitude': 0, 'longitude': 0, 'radius_m': 100}])
    asyncio.run(evaluator.update('tracker', 0, 0))
    evaluator.disable('z')
    assert evaluator.is_member('tracker', 'z') is None


def test_automation_zone_trigger_matches_normalized_event():
    automation = import_module('02_HCM.automation')
    engine = automation.AutomationEngine(None)
    trigger = {'type': 'zone', 'tracker_ref': 'tracker', 'zone_ref': 'zone', 'event': 'enter'}
    event = {'event_type': 'hcm_native.zone.enter', 'payload': {'tracker_ref': 'tracker', 'zone_ref': 'zone'}}
    assert engine._trigger_matches(trigger, event)
