from importlib import import_module


lcm = import_module('03_LCM.main')


def test_lcm_numeric_channel_map():
    agent = lcm.LCMAgent({})

    relay = agent._set_channel('1', {'value': True})
    assert relay['kind'] == 'relay'
    assert relay['physical'] == 'A1'
    assert relay['arbitration']['effective_state']['energized'] is True
    assert agent.relays.get('A1') is True

    lv = agent._set_channel('9', {'value': 25})
    assert lv['kind'] == 'lv_dimmer'
    assert lv['physical'] == '10-1'
    assert agent.lv_dimmers.snapshot()['10-1']['percent'] == 25

    last_lv = agent._set_channel('18', {'value': 45})
    assert last_lv['kind'] == 'lv_dimmer'
    assert last_lv['physical'] == '10-10'

    hv = agent._set_channel('19', {'value': 55})
    assert hv['kind'] == 'hv_dimmer'
    assert hv['physical'] == 'HV-1'
    assert hv['arbitration']['effective_state']['percent'] == 55.0
    assert agent.hv_dimmers.snapshot()['HV-1']['percent'] == 55

    hv_direct = agent._set_channel('HV-1', {'value': 40})
    assert hv_direct['kind'] == 'hv_dimmer'
    assert agent.hv_dimmers.snapshot()['HV-1']['percent'] == 40


def test_lcm_uses_simulated_analog_abstraction_until_pwm_contract_verified():
    agent = lcm.LCMAgent({})

    first = agent._set_channel('9', {'percent': 50})
    second = agent._set_channel('10', {'percent': 25})

    assert first['physical'] == '10-1'
    assert second['physical'] == '10-2'
    assert agent.i2c_bus.writes == []
    assert agent.peripherals.components['lcm_pwm_controller'].status == 'not_configured'


def test_lcm_dimmer_uses_global_min_max_bounds(monkeypatch):
    agent = lcm.LCMAgent({})
    agent.global_config.Lighting_Dimmer_Max_Percent = 60
    agent.global_config.Lighting_Dimmer_Min_Percent = 10

    high = agent._set_channel('10-1', {'percent': 95})
    low = agent._set_channel('10-2', {'percent': 1})

    assert high['percent'] == 60.0
    assert low['percent'] == 10.0


def test_lcm_physical_inventory_is_8_relays_10_analog_4_hv():
    agent = lcm.LCMAgent({})

    assert list(agent.relays.snapshot()) == [f'A{i}' for i in range(1, 9)]
    assert list(agent.lv_dimmers.snapshot()) == [f'10-{i}' for i in range(1, 11)]
    assert list(agent.hv_dimmers.snapshot()) == [f'HV-{i}' for i in range(1, 5)]
    assert '9' not in agent.relay_map
