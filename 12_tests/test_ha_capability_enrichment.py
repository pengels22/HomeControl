import asyncio
from importlib import import_module

import pytest

m = import_module('01_HCM.ha_importer')
enrich = import_module('01_HCM.ha_capability_enrichment').enrich_plan


class Services:
    def __init__(self, statuses): self.statuses = statuses; self.calls = []
    async def validate_capability(self, target, domain, service, arguments):
        self.calls.append((target, domain, service, arguments))
        return self.statuses.get((target, domain, service), {'status': 'SUPPORTED'})


@pytest.mark.asyncio
async def test_enrichment_validates_mapped_service_and_caches_repeated_targets():
    source = {'automations': [{'id': 'a', 'actions': [
        {'action': 'light.turn_on', 'target': {'entity_id': 'light.a'}},
        {'action': 'light.turn_on', 'target': {'entity_id': 'light.a'}},
    ]}]}
    plan = m.analyze_home_assistant(source, mappings={'light.a': 7})
    services = Services({(7, 'light', 'turn_on'): {'status': 'SUPPORTED'}})
    enriched = await enrich(plan, services)
    assert services.calls == [(7, 'light', 'turn_on', {}),]
    assert enriched['items'][0]['eligibility'] == m.READY_WITH_TRANSLATIONS
    assert enriched['items'][0]['nested'][2]['children'][0]['capability_status'] == 'SUPPORTED'


@pytest.mark.asyncio
async def test_enrichment_distinguishes_mismatch_unavailable_missing_and_invalid():
    statuses = {
        (1, 'light', 'turn_on'): {'status': 'TARGET_DOES_NOT_SUPPORT'},
        (2, 'media_player', 'select_source'): {'status': 'SUPPORTED_BUT_UNAVAILABLE'},
        (3, 'climate', 'set_hvac_mode'): {'status': 'SERVICE_NOT_REGISTERED'},
        (4, 'climate', 'set_temperature'): {'status': 'INVALID_ARGUMENT'},
    }
    source = {'automations': [{'id': 'a', 'actions': [
        {'action': 'light.turn_on', 'target': {'entity_id': 'light.a'}, 'data': {'brightness_pct': 50}},
        {'action': 'media_player.select_source', 'target': {'entity_id': 'media.a'}, 'data': {'source': 'x'}},
        {'action': 'climate.set_hvac_mode', 'target': {'entity_id': 'climate.a'}, 'data': {'hvac_mode': 'heat'}},
        {'action': 'climate.set_temperature', 'target': {'entity_id': 'climate.b'}, 'data': {'temperature': 70}},
    ]}]}
    plan = m.analyze_home_assistant(source, mappings={'light.a': 1, 'media.a': 2, 'climate.a': 3, 'climate.b': 4})
    enriched = await enrich(plan, Services(statuses))
    nodes = enriched['items'][0]['nested'][2]['children']
    assert [node['capability_status'] for node in nodes] == ['TARGET_DOES_NOT_SUPPORT', 'SUPPORTED_BUT_UNAVAILABLE', 'SERVICE_NOT_REGISTERED', 'INVALID_ARGUMENT']
    assert enriched['items'][0]['eligibility'] == m.BLOCKED_UNSUPPORTED


@pytest.mark.asyncio
async def test_unresolved_and_notification_targets_are_not_checked():
    source = {'automations': [{'id': 'a', 'actions': [
        {'action': 'light.turn_on', 'target': {'entity_id': 'light.unknown'}},
        {'action': 'notify.mobile_app_phone', 'data': {'message': 'x'}},
    ]}]}
    plan = m.analyze_home_assistant(source)
    services = Services({})
    enriched = await enrich(plan, services)
    assert services.calls == []
    nodes = enriched['items'][0]['nested'][2]['children']
    assert nodes[0]['status'] == m.NEEDS_MAPPING
    assert nodes[0]['capability_status'] == 'NOT_CHECKED'


@pytest.mark.asyncio
async def test_dynamic_arguments_are_deferred_to_runtime_validation():
    source = {'automations': [{'id': 'a', 'actions': [
        {'action': 'climate.set_temperature', 'target': {'entity_id': 'climate.a'},
         'data': {'temperature': "{{ states('sensor.target_temp') }}"}},
    ]}]}
    plan = m.analyze_home_assistant(source, mappings={'climate.a': 9})
    services = Services({(9, 'climate', 'set_temperature'): {'status': 'INVALID_ARGUMENT'}})
    enriched = await enrich(plan, services)
    node = enriched['items'][0]['nested'][2]['children'][0]
    assert node['capability_status'] == 'SUPPORTED'
    assert node['capability_results'][0]['runtime_value_validation_required'] is True
