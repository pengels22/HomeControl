from importlib import import_module
from pathlib import Path

import pytest

pinmap = import_module('07_servises.common.pinmap')
rcm = import_module('04_RCM.main')


def test_load_rcm_pinout_reads_mcp_addresses():
    entries = pinmap.load_pinout(Path('06_config/04_RCM/Pinout.md'))

    assert entries['A1'].hardware_address == 'MCP0 A0'
    assert entries['D8'].hardware_address == 'MCP1 B7'
    assert entries['E8'].function == 'Action Button'


def test_load_hcm_pinout_reads_fire_and_front_panel_pins():
    entries = pinmap.load_pinout(Path('06_config/01_HCM/Pinout.md'))

    assert entries['FIRE_DI'].hardware_address == 'Physical Pin 19 / GPIO28'
    assert entries['FIRE_3V3'].hardware_address == 'Physical Pin 17'
    assert entries['FIRE_GND'].hardware_address == 'Physical Pin 24'
    assert entries['LINK1_LED'].hardware_address == 'Physical Pin 3'
    assert entries['LINK2_LED'].hardware_address == 'Physical Pin 5'
    assert entries['STATUS_LED'].hardware_address == 'Physical Pin 7'
    assert entries['FAULT_LED'].hardware_address == 'Physical Pin 11'
    assert entries['ACTION_BUTTON'].hardware_address == 'Physical Pin 13'


def test_require_channels_rejects_missing_required_channel():
    entries = {'A1': pinmap.PinMapEntry('A1', 'MCP0 A0', 'Relay', '-')}

    with pytest.raises(ValueError, match='A2'):
        pinmap.require_channels(entries, ['A1', 'A2'])


@pytest.mark.asyncio
async def test_rcm_agent_reports_pinout_address_on_relay_command():
    agent = rcm.RCMAgent({})

    result = await agent.apply_command({'op': 'set_relay', 'channel': 'A1', 'value': True})

    assert result == {
        'ok': True,
        'channel': 'A1',
        'hardware_address': 'MCP0 A0',
        'value': True,
    }
