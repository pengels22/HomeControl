from copy import deepcopy
from importlib import import_module

import pytest


rcm = import_module('04_RCM.main')
lcm = import_module('03_LCM.main')
profiles = import_module('07_servises.common.hardware_profiles')


def _profile(module):
    path = '06_config/04_RCM/hardware_pins.yaml' if module == 'RCM' else '06_config/03_LCM/hardware_pins.yaml'
    profile = deepcopy(profiles.load_profile(path, module).data)
    profile['verification']['status'] = 'COMMISSIONED'
    profile['physical_output_enabled'] = True
    for section in profile['outputs'].values():
        if isinstance(section, dict) and ('channels' in section or 'mappings' in section):
            section['real_output_enabled'] = True
    return profile


@pytest.mark.asyncio
async def test_rcm_all_off_reaches_every_physical_relay():
    agent = rcm.RCMAgent({'io': {'mode': 'real'}, 'mock_hardware': True, 'hardware_profile': _profile('RCM')})
    await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True, 'physical_write_requested': True})
    result = await agent.apply_command({'op': 'all_off'})
    assert result['ok'] is True
    assert all(not value for value in agent.relays.snapshot().values())
    assert agent.driver_bundle['rcm_relays'].shadow == {0x20: 0xFFFF, 0x21: 0xFFFF}


@pytest.mark.asyncio
async def test_rcm_safety_shutdown_deenergizes_real_driver():
    agent = rcm.RCMAgent({'io': {'mode': 'real'}, 'mock_hardware': True, 'hardware_profile': _profile('RCM')})
    await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True, 'physical_write_requested': True})
    result = await agent.apply_command({'op': 'safety_state', 'conditions': {'communication_loss': True}})
    assert result['ok'] is True
    assert agent.driver_bundle['rcm_relays'].read_channel(0) is False
    assert agent.relays.get('A1') is False


@pytest.mark.asyncio
async def test_lcm_canonical_ids_reach_each_physical_driver():
    agent = lcm.LCMAgent({'io': {'mode': 'real'}, 'mock_hardware': True, 'hardware_profile': _profile('LCM')})
    for channel, value in [('A1', True), ('10-1', 25), ('10-10', 75), ('HV-1', 30), ('HV-4', 60)]:
        result = await agent.apply_command({'op': 'set_channel', 'channel': channel, 'value': value, 'percent': value, 'physical_write_requested': True})
        assert result['ok'] is True
    assert agent.driver_bundle['lcm_relays'].read_channel(0) is True
    assert agent.driver_bundle['lcm_pwm'].values[0] == round(25 * 4095 / 100)
    assert agent.driver_bundle['lcm_pwm'].values[9] == round(75 * 4095 / 100)
    assert agent.driver_bundle['shelly_1'].calls[-1] == {'component': 'light:0', 'percent': 30.0}
    assert agent.driver_bundle['shelly_2'].calls[-1] == {'component': 'light:1', 'percent': 60.0}


@pytest.mark.asyncio
async def test_lcm_confidence_distinguishes_real_software_and_device_commands():
    real = lcm.LCMAgent({'io': {'mode': 'real'}, 'mock_hardware': True, 'hardware_profile': _profile('LCM')})
    software = await real.apply_command({'op': 'set_channel', 'channel': 'A1', 'value': True})
    assert software['state_confidence_label'] == 'COMMANDED'
    physical = await real.apply_command({'op': 'set_channel', 'channel': 'HV-1', 'percent': 20, 'physical_write_requested': True})
    assert physical['state_confidence_label'] == 'DEVICE_REPORTED'
    simulated = lcm.LCMAgent({})
    result = await simulated.apply_command({'op': 'set_channel', 'channel': '10-1', 'percent': 20})
    assert result['state_confidence_label'] == 'SIMULATED'


@pytest.mark.asyncio
async def test_lcm_safety_shutdown_attempts_relay_pwm_and_shelly_off():
    agent = lcm.LCMAgent({'io': {'mode': 'real'}, 'mock_hardware': True, 'hardware_profile': _profile('LCM')})
    for channel, value in [('A1', True), ('10-1', 50), ('HV-1', 50)]:
        await agent.apply_command({'op': 'set_channel', 'channel': channel, 'value': value, 'percent': value, 'physical_write_requested': True})
    result = await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})
    assert result['ok'] is True
    assert agent.driver_bundle['lcm_relays'].read_channel(0) is False
    assert agent.driver_bundle['lcm_pwm'].values[0] == 0
    assert {'component': 'light:0', 'percent': 0.0} in agent.driver_bundle['shelly_1'].calls


def test_real_factory_requires_explicit_i2c_mapping():
    factory = import_module('07_servises.common.hardware_factory')
    with pytest.raises(ValueError, match='explicit Linux bus mapping'):
        factory.build_hardware_bundle('RCM', {'hardware_mode': 'real'}, {'outputs': {}})


def test_bench_testing_is_exact_target_only_and_not_a_production_gate():
    commissioning = import_module('07_servises.common.commissioning')
    profile = {'module_type': 'RCM', 'verification': {'status': 'BENCH_TESTING'}, 'outputs': {'relays': {'channels': ['A1']}}}
    assert commissioning.physical_write_allowed(profile, 'A1') is False
    assert commissioning.bench_test_write_allowed(profile, 'A1', True, 'RCM', 'A1') is True
    assert commissioning.bench_test_write_allowed(profile, 'A1', True, 'RCM', '*') is False
    assert commissioning.bench_test_write_allowed(profile, 'A1', True, 'LCM', 'A1') is False


def test_profile_lifecycle_accepts_bench_testing_but_keeps_it_nonphysical():
    for status in ('DESIGN_APPROVED', 'BENCH_TESTING', 'BENCH_TESTED', 'SIMULATED'):
        profile = _profile('RCM')
        profile['verification']['status'] = status
        profile['physical_output_enabled'] = False
        validated = profiles.validate_profile(profile, 'RCM')
        commissioning = import_module('07_servises.common.commissioning')
        assert commissioning.physical_write_allowed(validated.data, 'A1') is False


def test_hcm_binding_execution_mode_is_the_only_physical_wire_selector():
    devices = import_module('01_HCM.devices')
    row = {'metadata': {'execution_mode': 'physical'}, 'channel': 'A1'}
    assert devices._payload(row, {'op': 'set_relay', 'value': True})['physical_write_requested'] is True
    simulated = devices._payload({'metadata': {}, 'channel': 'A1'}, {'op': 'set_relay', 'value': True, 'physical_write_requested': True})
    assert 'physical_write_requested' not in simulated
