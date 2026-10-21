from importlib import import_module

import pytest


hil = import_module('13_hardware_tests.hil_runner')
drivers = import_module('08_servises.common.physical_drivers')


def bench_profile(module_type, channels):
    section = {'channels': list(channels), 'real_output_enabled': False}
    return {
        'module_type': module_type,
        'verification': {'status': 'BENCH_TESTING'},
        'physical_output_enabled': False,
        'outputs': {'relays': section},
    }


def test_rcm_channel_sequence_uses_production_driver_and_finishes_off():
    transport = drivers.MockI2CTransport()
    relay = drivers.XL9535RelayDriver(drivers.LockedI2C(transport))
    relay.initialize()
    bundle = type('Bundle', (), {'rcm_relays': relay, 'lcm_relays': None, 'lcm_pwm': None})()
    profile = bench_profile('RCM', ['A1'])
    result = hil.cycle_outputs('RCM', profile, bundle, ['A1'], dwell_s=0, sleep=lambda _: None)
    assert result[0]['pass'] is True
    assert relay.read_channel(0) is False


def test_cleanup_attempts_every_output_after_a_test_exception():
    transport = drivers.MockI2CTransport()
    relay = drivers.XL9535RelayDriver(drivers.LockedI2C(transport))
    relay.initialize()
    relay.set_channel(0, True)
    result = hil.all_off('RCM', type('Bundle', (), {'rcm_relays': relay})())
    assert len(result) == 32
    assert relay.read_channel(0) is False
    assert all(item['ok'] for item in result)


def test_lcm_pwm_sequence_reports_register_readback_and_zero_final():
    transport = drivers.MockI2CTransport()
    bus = drivers.LockedI2C(transport)
    pwm = drivers.PCA9685Driver(bus)
    pwm.initialize()
    bundle = type('Bundle', (), {'rcm_relays': None, 'lcm_relays': None, 'lcm_pwm': pwm})()
    profile = {'module_type': 'LCM', 'verification': {'status': 'BENCH_TESTING'}, 'physical_output_enabled': False,
               'outputs': {'analog_0_10v': {'channels': ['10-1'], 'real_output_enabled': False}}}
    result = hil.cycle_outputs('LCM', profile, bundle, ['10-1'], dwell_s=0, sleep=lambda _: None)
    assert result[0]['pass'] is True
    assert [step['requested_percent'] for step in result[0]['steps']] == [0, 25, 50, 75, 100, 0]
    assert result[0]['steps'][-1]['readback'] == 0


def test_gate_rejects_non_bench_profile():
    profile = bench_profile('RCM', ['A1'])
    profile['verification']['status'] = 'DESIGN_APPROVED'
    with pytest.raises(hil.HILConfigurationError):
        hil._bench_allowed(profile, 'RCM', 'A1')
