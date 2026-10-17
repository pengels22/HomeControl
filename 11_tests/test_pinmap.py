from importlib import import_module
from pathlib import Path

import pytest

pinmap = import_module('07_servises.common.pinmap')
rcm = import_module('04_RCM.main')
commissioning = import_module('07_servises.common.commissioning')


def test_load_rcm_pinout_is_no_longer_the_authoritative_source():
    entries = pinmap.load_pinout(Path('06_config/04_RCM/Pinout.md'))
    assert entries == {}


def test_load_hcm_pinout_reads_fire_and_front_panel_pins():
    entries = pinmap.load_pinout(Path('06_config/01_HCM/Pinout.md'))
    assert entries == {}


def test_require_channels_rejects_missing_required_channel():
    entries = {'A1': pinmap.PinMapEntry('A1', 'MCP0 A0', 'Relay', '-')}

    with pytest.raises(ValueError, match='A2'):
        pinmap.require_channels(entries, ['A1', 'A2'])


@pytest.mark.asyncio
async def test_rcm_agent_reports_pinout_address_on_relay_command():
    agent = rcm.RCMAgent({})

    result = await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True})

    assert result['ok'] is True
    assert result['channel'] == 'A1'
    assert result['hardware_address'] == 'relay_card_1 index 0'
    assert result['value'] is True
    assert result['requested_value'] is True
    assert result['arbitration']['effective_state']['energized'] is True


@pytest.mark.asyncio
async def test_rcm_simulation_command_never_uses_physical_output_path():
    agent = rcm.RCMAgent({'io_mode': 'simulated'})

    result = await agent.apply_command({
        'op': 'simulate_relay',
        'channel': 'A1',
        'value': True,
        'simulation': True,
        'physical_outputs_enabled': False,
    })

    assert result == {
        'ok': True,
        'channel': 'A1',
        'value': True,
        'simulation': True,
        'physical_outputs_commanded': False,
        'state_confidence': 'simulated_commanded_only',
    }


@pytest.mark.asyncio
async def test_rcm_simulation_command_is_rejected_in_real_io_mode():
    agent = rcm.RCMAgent({'io_mode': 'real'})

    result = await agent.apply_command({
        'op': 'simulate_relay',
        'channel': 'A1',
        'value': True,
        'simulation': True,
        'physical_outputs_enabled': False,
    })

    assert result['ok'] is False
    assert result['physical_outputs_commanded'] is False
    assert agent.relays.get('A1') is False


def test_rcm_uses_global_relay_count_and_default_state():
    agent = rcm.RCMAgent({'relay_count': 2, 'default_relay_on': True})

    assert agent.relays.snapshot() == {'A1': True, 'A2': True}


def test_physical_bench_does_not_commission_without_explicit_channel_allowlist():
    profile = {
        'physical_output_enabled': True,
        'outputs': {'relays': {'real_output_enabled': True, 'channels': ['A1']}},
    }
    assert commissioning.physical_write_allowed(profile, 'A1') is False
    profile['outputs']['relays']['commissioned_channels'] = ['A1']
    assert commissioning.physical_write_allowed(profile, 'A1') is True
    assert commissioning.physical_write_allowed(profile, 'A2') is False


@pytest.mark.asyncio
async def test_uncommissioned_physical_request_is_rejected_without_output_command():
    agent = rcm.RCMAgent({'io_mode': 'real'})
    result = await agent.apply_command({
        'op': 'set_relay', 'channel': 'A1', 'value': True, 'physical_write_requested': True,
    })
    assert result['ok'] is False
    assert result['physical_outputs_commanded'] is False
    assert agent.relays.get('A1') is False
