from importlib import import_module

import pytest

simulator = import_module('10_scripts.simulate_homecontrol')


@pytest.mark.asyncio
async def test_mac_simulator_builds_module_state_and_rmc_frames():
    sim = simulator.HomeControlSimulator()

    await sim.tick_rmc()
    sim.hvac.state.mode = simulator.hvac_mod.Mode.COOL
    sim.hvac.state.setpoint_f = 70
    sim.hvac.rooms['Office'].temperature_f = 76
    await sim.hvac.evaluate()
    state = await sim.state()

    assert 'rcm' in state
    assert 'lcm' in state
    assert 'sim' in state
    assert state['hcm']['hvac']['mode'] == 'COOL'
    assert state['hcm']['hvac']['cool'] is True
    assert state['hcm']['pairing']['payload'] == 'HC1:HCM01:482913'
    assert state['hcm']['pairing']['format'] == 'HC-CIRCULAR-PAIR-1'
    assert state['sim']['rmc_nodes']


@pytest.mark.asyncio
async def test_simulator_rcm_lock_blocks_relay_change():
    sim = simulator.HomeControlSimulator()
    sim.rcm_locks['A1'] = True

    result = await sim.set_rcm_relay('A1', True)

    assert result == {'ok': False, 'locked': True, 'channel': 'A1'}
    assert sim.rcm.relays.get('A1') is False


@pytest.mark.asyncio
async def test_simulator_lcm_dimmer_fades_to_target():
    sim = simulator.HomeControlSimulator()

    result = await sim.set_lcm_dimmer_fade('10-1', 75, duration_s=0.01, steps=2)
    await sim.lcm_fades['10-1']

    assert result == {'ok': True, 'channel': '10-1', 'target_percent': 75.0, 'fade_s': 0.01}
    assert sim.lcm.lv_dimmers.snapshot()['10-1']['percent'] == 75


@pytest.mark.asyncio
async def test_simulator_lcm_relay_control():
    sim = simulator.HomeControlSimulator()

    result = await sim.set_lcm_relay('A1', True)

    assert result['ok'] is True
    assert result['kind'] == 'relay'
    assert sim.lcm.relays.get('A1') is True


@pytest.mark.asyncio
async def test_simulator_lcm_channel_names_are_editable():
    sim = simulator.HomeControlSimulator()

    result = sim.set_lcm_name('10-1', 'Kitchen Cove')
    state = await sim.state()

    assert result == {'ok': True, 'channel': '10-1', 'name': 'Kitchen Cove'}
    assert state['lcm']['names']['10-1'] == 'Kitchen Cove'


@pytest.mark.asyncio
async def test_simulator_rcm_channel_names_are_editable():
    sim = simulator.HomeControlSimulator()

    result = sim.set_rcm_name('A1', 'Kitchen Relay')
    state = await sim.state()

    assert result == {'ok': True, 'channel': 'A1', 'name': 'Kitchen Relay'}
    assert state['rcm']['names']['A1'] == 'Kitchen Relay'
