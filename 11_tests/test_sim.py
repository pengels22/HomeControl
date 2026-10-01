from importlib import import_module

import pytest

sim = import_module('02_SIM.main')
common_can = import_module('07_servises.common.can')


def test_sim_builds_three_can_interfaces_from_config():
    agent = sim.SIMAgent({
        'can_interfaces': [
            {'name': 'can0', 'label': 'CAN A', 'bitrate': 125000, 'enabled': True},
            {'name': 'can1', 'label': 'CAN B', 'bitrate': 125000, 'enabled': True},
            {'name': 'can2', 'label': 'CAN C', 'bitrate': 125000, 'enabled': True},
        ]
    })

    state = agent.can_network.snapshot()

    assert list(state) == ['can0', 'can1', 'can2']
    assert state['can0']['label'] == 'CAN A'
    assert state['can2']['bitrate'] == 125000


@pytest.mark.asyncio
async def test_sim_configure_can_dry_run_returns_ip_commands():
    agent = sim.SIMAgent({
        'can_interfaces': [
            {'name': 'can0', 'label': 'CAN A', 'bitrate': 125000, 'enabled': True},
        ]
    })

    result = await agent.apply_command({'op': 'configure_can', 'apply': False})

    assert result['ok'] is True
    assert result['can']['can0']['applied'] is False
    assert ['ip', 'link', 'set', 'can0', 'type', 'can', 'bitrate', '125000'] in result['can']['can0']['commands']


@pytest.mark.asyncio
async def test_sim_records_injected_can_frame():
    agent = sim.SIMAgent({
        'can_interfaces': [
            {'name': 'can0', 'label': 'CAN A', 'bitrate': 125000, 'enabled': True},
        ]
    })

    await agent.apply_command({'op': 'inject_can_frame', 'interface': 'can0', 'arbitration_id': 123, 'data': [1, 2, 3]})

    frame = agent.can_network.snapshot()['can0']['last_frame']
    assert frame['arbitration_id'] == 123
    assert frame['data'] == [1, 2, 3]


def test_rmc_telemetry_codec_matches_firmware_layout():
    arbitration_id, data = common_can.encode_rmc_telemetry(
        3,
        presence=True,
        temperature_c=22,
        humidity_pct=47,
        lux=512,
        aqi=2,
    )

    decoded = common_can.decode_rmc_frame(arbitration_id, data)

    assert arbitration_id == 0x130
    assert decoded['kind'] == 'telemetry'
    assert decoded['address'] == 3
    assert decoded['presence'] is True
    assert decoded['temperature_c'] == 22
    assert decoded['humidity_pct'] == 47
    assert decoded['lux'] == 512
    assert decoded['aqi'] == 2


@pytest.mark.asyncio
async def test_sim_updates_rmc_node_from_firmware_telemetry_frame():
    agent = sim.SIMAgent({
        'can_interfaces': [
            {'name': 'can0', 'label': 'CAN A', 'bitrate': 125000, 'enabled': True},
        ]
    })
    arbitration_id, data = common_can.encode_rmc_telemetry(
        2,
        presence=False,
        temperature_c=21,
        humidity_pct=50,
        lux=300,
        aqi=1,
    )

    result = await agent.apply_command({
        'op': 'inject_can_frame',
        'interface': 'can0',
        'arbitration_id': arbitration_id,
        'data': data,
    })

    assert result['decoded']['address'] == 2
    assert agent.rmc_nodes['2']['temperature_f'] == 69.8
    assert agent.rmc_nodes['2']['lux'] == 300
