import pytest
from importlib import import_module

security = import_module('02_HCM.security_alarm')
importer = import_module('02_HCM.ha_importer')


@pytest.mark.asyncio
async def test_mock_alarm_arm_transition_and_idempotency():
    controller = security.MockAlarmController()
    layer = security.SecurityAlarmLayer(controller, entity_ref=17)
    result = await layer.arm('away')
    assert result['status'] == 'accepted' and result['state'] == 'armed_away'
    assert (await layer.arm('away'))['status'] == 'no_change'


@pytest.mark.asyncio
async def test_disarm_requires_credential_and_automation_policy():
    controller = security.MockAlarmController()
    layer = security.SecurityAlarmLayer(controller, entity_ref=17)
    assert (await layer.disarm(source='automation', credential_configured=True))['status'] == 'policy_rejected'
    assert (await layer.disarm(credential_configured=False))['status'] == 'credential_required'
    await layer.arm('away')
    result = await layer.disarm(credential_ref='synthetic-ref', credential_configured=True)
    assert result['status'] == 'accepted' and result['credential_present'] is True
    assert 'synthetic-ref' not in str(result)


@pytest.mark.asyncio
async def test_alarm_dry_run_capability_and_unavailable():
    controller = security.MockAlarmController(capabilities=security.AlarmCapabilities(
        arm_modes=frozenset({security.AlarmMode.HOME}), disarm_requires_credential=False))
    layer = security.SecurityAlarmLayer(controller, entity_ref=17)
    assert (await layer.arm('away'))['status'] == 'policy_rejected'
    assert (await layer.arm('home', dry_run=True))['status'] == 'dry_run'
    controller.available = False
    assert (await layer.arm('home'))['status'] == 'controller_unavailable'


def test_alarm_import_redacts_code_and_requires_security_mapping():
    plan = importer.analyze_home_assistant({'automations': [{
        'id': 'synthetic-alarm',
        'actions': [{'service': 'alarm_control_panel.alarm_arm_away',
                     'target': {'entity_id': 'alarm_control_panel.panel'},
                     'data': {'code': 'synthetic-secret'}}]
    }]})
    item = plan['items'][0]
    assert item['security_review_required'] is True
    assert item['eligibility'] == 'BLOCKED_MAPPING'
    assert 'synthetic-secret' not in str(plan)
    node = item['nested'][2]['children'][0]
    assert node['code_form'] == 'literal'
    assert node['reason'] == 'SECURITY_CREDENTIAL_MAPPING_REQUIRED'
    assert node['native']['service_data'] == {}


def test_alarm_import_accepts_only_explicit_credential_reference_mapping():
    plan = importer.analyze_home_assistant({'automations': [{
        'id': 'synthetic-alarm',
        'actions': [{'service': 'alarm_control_panel.alarm_arm_home',
                     'target': {'entity_id': 'alarm_control_panel.panel'},
                     'data': {'code': 'synthetic-secret'}}]
    }]}, mappings={'alarm_control_panel.panel': 9,
                   'alarm_credential:alarm_control_panel.panel': 'credential-ref'})
    node = plan['items'][0]['nested'][2]['children'][0]
    assert node['status'] == 'TRANSLATED'
    assert node['native']['service_data']['credential_ref'] == 'credential-ref'
    assert 'synthetic-secret' not in str(plan)
