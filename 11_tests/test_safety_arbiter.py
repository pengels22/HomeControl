import asyncio
from importlib import import_module

import pytest


arb = import_module('07_servises.common.safety_arbiter')
fire_input = import_module('07_servises.common.fire_input')
rcm = import_module('04_RCM.main')
lcm = import_module('03_LCM.main')
sim_mod = import_module('02_SIM.main')


def decision(channel, command, conditions=None, emergency=None, hvac=None):
    safety = arb.SafetyArbiter(
        emergency_lighting_channels=set(emergency or []),
        hvac_shutdown_channels=set(hvac or []),
    )
    safety.update_conditions(conditions or {})
    return safety.decide(arb.OutputRequest(None, channel, command, 'user'))


def test_normal_automation_energizes_allowed_output():
    result = decision('A1', {'op': 'set_relay', 'value': True})

    assert result.effective_state.energized is True
    assert result.final_command['value'] is True
    assert result.inhibited is False


def test_maintenance_lockout_prevents_energization():
    result = decision('A1', {'op': 'set_relay', 'value': True}, {'maintenance_lockout': True})

    assert result.effective_state.energized is False
    assert result.final_command['value'] is False
    assert result.inhibited is True
    assert result.reason == 'maintenance_lockout'


def test_fire_energizes_designated_emergency_lighting_without_lockout():
    result = decision('A1', {'op': 'light', 'percent': 0, 'value': False}, {'fire_active': True}, emergency={'A1'})

    assert result.effective_state.energized is True
    assert result.final_command['percent'] == 100.0
    assert result.reason == 'fire_active'


def test_fire_deenergizes_hvac_shutdown_relay_coil():
    result = decision('A2', {'op': 'set_relay', 'value': True}, {'fire_active': True}, hvac={'A2'})

    assert result.effective_state.energized is False
    assert result.final_command['value'] is False


def test_fire_cannot_energize_during_maintenance_lockout():
    result = decision(
        'A1',
        {'op': 'light', 'percent': 100, 'value': True},
        {'fire_active': True, 'maintenance_lockout': True},
        emergency={'A1'},
    )

    assert result.effective_state.energized is False
    assert result.reason == 'maintenance_lockout'


def test_unknown_fire_input_is_conservative():
    result = decision('A1', {'value': True}, {'fire_input_fault': True})

    assert result.final_command['value'] is False
    assert result.fault_state == 'fire_input_fault'


def test_communication_loss_is_conservative():
    result = decision('A1', {'value': True}, {'communication_loss': True})

    assert result.final_command['value'] is False
    assert result.fault_state == 'communication_loss'


def test_feedback_mismatch_is_reported():
    safety = arb.SafetyArbiter()
    result = safety.decide(
        arb.OutputRequest(None, 'A1', {'value': False}, 'user'),
        feedback_state=arb.OutputState(True, 100),
    )

    assert result.fault_state == 'feedback_mismatch'


def test_simultaneous_fire_lockout_and_user_command_keeps_final_inhibit():
    safety = arb.SafetyArbiter(emergency_lighting_channels={'A1'})
    safety.update_conditions({'fire_active': True, 'maintenance_lockout': True})
    results = [
        safety.decide(arb.OutputRequest(None, 'A1', {'value': True, 'percent': 100}, src))
        for src in ('user', 'rules', 'local_override', 'life_safety')
    ]

    assert all(not result.effective_state.energized for result in results)
    assert all(result.reason == 'maintenance_lockout' for result in results)


def test_safe_restart_does_not_replay_old_energized_request_before_conditions():
    safety = arb.SafetyArbiter()
    safety.update_conditions({'maintenance_lockout': True})

    result = safety.decide(arb.OutputRequest(None, 'A1', {'value': True}, 'user'))

    assert result.final_command['value'] is False
    assert result.reason == 'maintenance_lockout'


def test_fire_input_debounce_rejects_bounce_until_stable():
    input_ = fire_input.DebouncedFireInput(alarm_level=True, debounce_seconds=0.25)

    assert input_.sample(False, 0.0).fire_active is False
    assert input_.sample(True, 0.05).fire_active is False
    assert input_.sample(False, 0.10).fire_active is False
    assert input_.sample(True, 0.20).fire_active is False
    stable = input_.sample(True, 0.46)

    assert stable.changed is True
    assert stable.fire_active is True


@pytest.mark.asyncio
async def test_rcm_direct_module_api_cannot_bypass_lockout():
    agent = rcm.RCMAgent({})
    await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})

    result = await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True})

    assert result['value'] is False
    assert result['arbitration']['reason'] == 'maintenance_lockout'
    assert agent.relays.get('A1') is False


@pytest.mark.asyncio
async def test_rcm_lockout_immediately_deenergizes_existing_outputs():
    agent = rcm.RCMAgent({})
    await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True})

    result = await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})
    state = await agent.collect_state()

    assert result['arbitration']
    assert state['relays']['A1'] is False


@pytest.mark.asyncio
async def test_lcm_direct_dimmer_command_cannot_bypass_lockout():
    agent = lcm.LCMAgent({})
    await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})

    result = await agent.apply_command({'op': 'set_dimmer', 'channel': '10-1', 'percent': 75})

    assert result['percent'] == 0.0
    assert result['arbitration']['reason'] == 'maintenance_lockout'


@pytest.mark.asyncio
async def test_lcm_lockout_immediately_deenergizes_existing_outputs():
    agent = lcm.LCMAgent({})
    await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True})
    await agent.apply_command({'op': 'set_dimmer', 'channel': '10-1', 'percent': 70})

    result = await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})
    state = await agent.collect_state()

    assert result['arbitration']
    assert state['relays']['A1'] is False
    assert state['lv_dimmers']['10-1']['percent'] == 0.0


@pytest.mark.asyncio
async def test_sim_hexa_output_cannot_bypass_lockout():
    cfg = sim_mod.common_cfg.load_yaml(sim_mod.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    cfg['io'] = {'mode': 'simulated'}
    agent = sim_mod.SIMAgent(cfg)
    await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})

    result = await agent.apply_command({'op': 'set_hexa_12v', 'channel': 'sw1', 'value': True})

    assert result['value'] is False
    assert result['arbitration']['reason'] == 'maintenance_lockout'


@pytest.mark.asyncio
async def test_sim_hexa_inputs_are_not_part_of_lockout():
    cfg = sim_mod.common_cfg.load_yaml(sim_mod.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    cfg['io'] = {'mode': 'simulated'}
    agent = sim_mod.SIMAgent(cfg)
    await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})

    command_result = await agent.apply_command({'op': 'set_hexa_dio', 'channel': 'dio1', 'value': True})
    input_result = await agent.apply_command({'op': 'inject_hexa_di', 'channel': 'dio1', 'value': True})

    assert command_result == {'ok': False, 'error': 'channel_is_input', 'channel': 'dio1', 'direction': 'input'}
    assert input_result == {'ok': True, 'channel': 'dio1', 'value': True, 'direction': 'input'}
    assert 'DIO1' not in agent.safety.snapshot()['outputs']
    assert (await agent.collect_state())['hexa_board']['dio']['dio1']['value'] is True


@pytest.mark.asyncio
async def test_sim_hexa_restart_does_not_reenergize_after_lockout():
    cfg = sim_mod.common_cfg.load_yaml(sim_mod.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    cfg['io'] = {'mode': 'simulated'}
    agent = sim_mod.SIMAgent(cfg)

    restart = asyncio.ensure_future(agent.apply_command({'op': 'restart_hexa_12v', 'channel': 'sw1', 'delay_s': 0.05}))
    await asyncio.sleep(0)
    await agent.apply_command({'op': 'safety_state', 'conditions': {'maintenance_lockout': True}})
    result = await restart
    state = await agent.collect_state()

    assert result['restarted'] is False
    assert result['cancelled'] is True
    assert state['hexa_board']['switching_12v']['sw1']['value'] is False
