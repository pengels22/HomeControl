from importlib import import_module


lcm = import_module('03_LCM.main')


def test_lcm_numeric_channel_map():
    agent = lcm.LCMAgent({})

    relay = agent._set_channel('1', {'value': True})
    assert relay['kind'] == 'relay'
    assert relay['physical'] == 'A1'
    assert agent.relays.get('A1') is True

    hv = agent._set_channel('13', {'value': 55})
    assert hv['kind'] == 'hv_dimmer'
    assert hv['physical'] == 'HV-1'
    assert agent.hv_dimmers.snapshot()['HV-1']['percent'] == 55

    hv_direct = agent._set_channel('HV-1', {'value': 40})
    assert hv_direct['kind'] == 'hv_dimmer'
    assert agent.hv_dimmers.snapshot()['HV-1']['percent'] == 40

    lv = agent._set_channel('17', {'value': 25})
    assert lv['kind'] == 'lv_dimmer'
    assert lv['physical'] == '10-1'
    assert agent.lv_dimmers.snapshot()['10-1']['percent'] == 25


def test_lcm_lv_dimmers_share_dac_address_across_mux_channels():
    agent = lcm.LCMAgent({})

    first = agent._set_channel('17', {'percent': 50})
    second = agent._set_channel('18', {'percent': 25})

    assert first['dac_address'] == 0x60
    assert first['mux_channel'] == 0
    assert second['dac_address'] == 0x60
    assert second['mux_channel'] == 1
    assert agent.i2c_bus.writes[0] == (0x70, 0x01, 0)
    assert agent.i2c_bus.writes[2] == (0x70, 0x02, 0)
