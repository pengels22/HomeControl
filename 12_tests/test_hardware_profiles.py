from importlib import import_module
from pathlib import Path

import pytest


profiles = import_module('08_servises.common.hardware_profiles')


@pytest.mark.parametrize('module_type', ['HCM', 'SIM', 'LCM', 'RCM'])
def test_authoritative_profiles_have_complete_processor_headers_and_inhibit_outputs(module_type):
    profile = profiles.load_profile(profiles.profile_path(Path(__file__).parents[1], module_type), module_type)
    assert len(profile.data['processor_header']) == profile.data['processor']['header_pins']
    assert profile.physical_output_enabled is False
    assert profile.verification_status in {'DESIGN_APPROVED', 'SIMULATED'}


def test_lcm_profile_uses_new_pca9685_and_22_channel_inventory():
    profile = profiles.load_profile(profiles.profile_path(Path(__file__).parents[1], 'LCM'), 'LCM')
    outputs = profile.data['outputs']
    assert outputs['analog_0_10v']['address'] == 0x40
    assert outputs['analog_0_10v']['pwm_channels'] == list(range(10))
    assert outputs['analog_0_10v']['reserved_pwm_channels'] == list(range(10, 16))
    assert outputs['relays']['channels'] == [f'A{i}' for i in range(1, 9)]
    assert outputs['hv_dimmers']['channels'] == [f'HV-{i}' for i in range(1, 5)]


def test_rcm_profile_uses_two_xl9535_cards_and_preserves_logical_names():
    profile = profiles.load_profile(profiles.profile_path(Path(__file__).parents[1], 'RCM'), 'RCM')
    mapping = profile.data['outputs']['relays']['mappings']
    assert mapping['A1'] == {'device': 'relay_card_1', 'index': 0}
    assert mapping['B8'] == {'device': 'relay_card_1', 'index': 15}
    assert mapping['C1'] == {'device': 'relay_card_2', 'index': 0}
    assert mapping['D8'] == {'device': 'relay_card_2', 'index': 15}


def test_profile_rejects_duplicate_i2c_addresses():
    data = {
        'schema_version': 1,
        'module_type': 'TEST',
        'processor': {'header_pins': 1},
        'processor_header': {'1': {'function': 'GND', 'verification': 'UNVERIFIED'}},
        'buses': {'i2c': {'a': {'bus': 'I2C', 'address': '0x20'}, 'b': {'bus': 'I2C', 'address': '0x20'}}},
    }
    with pytest.raises(profiles.HardwareProfileError, match='I2C address conflict'):
        profiles.validate_profile(data)


def test_profile_rejects_real_outputs_before_commissioning():
    data = {
        'schema_version': 1,
        'module_type': 'TEST',
        'physical_output_enabled': True,
        'verification': {'status': 'DESIGN_APPROVED'},
        'processor': {'header_pins': 1},
        'processor_header': {'1': {'function': 'GND', 'verification': 'UNVERIFIED'}},
    }
    with pytest.raises(profiles.HardwareProfileError, match='before commissioning'):
        profiles.validate_profile(data)
