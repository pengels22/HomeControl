from importlib import import_module
from urllib.parse import parse_qs, urlparse
from types import SimpleNamespace

import pytest

simulator = import_module('11_scripts.simulate_homecontrol')


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
    assert state['hcm']['pairing']['payload'].startswith('HC2:')
    assert sim.verify_pairing_payload(state['hcm']['pairing']['payload'])
    assert state['hcm']['pairing']['format'] == 'HC-CIRCULAR-PAIR-1'
    assert state['sim']['rmc_nodes']


@pytest.mark.asyncio
async def test_simulator_preview_disables_both_mode_specific_restart_lockouts():
    sim = simulator.HomeControlSimulator()

    assert sim.hvac.COOL_RESTART_LOCKOUT_S == 0
    assert sim.hvac.HEAT_RESTART_LOCKOUT_S == 0


def test_pairing_qr_payload_is_actionable_url_with_secure_payload():
    sim = simulator.HomeControlSimulator()

    pairing = sim.pairing_glyph()
    parsed = urlparse(pairing['qr_payload'])
    payload = parse_qs(parsed.query)['payload'][0]

    assert parsed.scheme == 'http'
    assert parsed.hostname not in (None, '0.0.0.0')
    assert parsed.port == 8088
    assert parsed.path == '/pair'
    assert payload == pairing['payload']
    assert payload.startswith('HC2:')
    assert pairing['qr_size'] == len(pairing['qr_matrix'])
    assert sim.verify_pairing_payload(payload)


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
async def test_simulator_lcm_fade_uses_global_defaults(monkeypatch):
    real_loader = simulator.common_global_config.load_global_config

    def fake_loader(component):
        cfg = real_loader(component)
        if component == 'LCM':
            values = cfg.as_dict()
            values['Lighting_Default_Fade_Time'] = 20
            values['Lighting_Default_Fade_Steps'] = 2
            return SimpleNamespace(**values)
        return cfg

    monkeypatch.setattr(simulator.common_global_config, 'load_global_config', fake_loader)
    sim = simulator.HomeControlSimulator()

    result = await sim.set_lcm_dimmer_fade('10-1', 50)
    await sim.lcm_fades['10-1']

    assert result['fade_s'] == 0.02
    assert sim.lcm.lv_dimmers.snapshot()['10-1']['percent'] == 50


@pytest.mark.asyncio
async def test_simulator_lockout_cancels_lcm_fades_and_sim_outputs_only():
    sim = simulator.HomeControlSimulator()

    await sim.sim.apply_command({'op': 'set_hexa_dio', 'channel': 'dio3', 'value': True})
    await sim.sim.apply_command({'op': 'set_hexa_12v', 'channel': 'sw1', 'value': True})
    await sim.sim.apply_command({'op': 'inject_hexa_di', 'channel': 'dio1', 'value': True})
    await sim.set_lcm_dimmer_fade('10-1', 75, duration_s=1, steps=10)

    result = await sim.set_maintenance_lockout(True)
    state = await sim.state()

    assert result['ok'] is True
    assert sim.lcm_fades == {}
    assert state['sim']['hexa_board']['dio']['dio1']['value'] is True
    assert state['sim']['hexa_board']['dio']['dio3']['value'] is False
    assert state['sim']['hexa_board']['switching_12v']['sw1']['value'] is False


@pytest.mark.asyncio
async def test_simulator_refuses_new_lcm_fade_during_lockout():
    sim = simulator.HomeControlSimulator()

    await sim.set_maintenance_lockout(True)
    result = await sim.set_lcm_dimmer_fade('10-1', 75, duration_s=0.01, steps=2)

    assert result['ok'] is False
    assert result['inhibited'] is True
    assert result['arbitration']['reason'] == 'maintenance_lockout'
    assert '10-1' not in sim.lcm_fades


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
