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

    lv = agent._set_channel('17', {'value': 25})
    assert lv['kind'] == 'lv_dimmer'
    assert lv['physical'] == '10-1'
    assert agent.lv_dimmers.snapshot()['10-1']['percent'] == 25
