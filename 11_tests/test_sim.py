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


def test_sim_can_setup_plan_loads_gs_usb_for_hexa_board():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')

    plan = common_can.configure_sync(cfg, apply=False)

    assert plan['can0']['hardware'] == 'FYSETC Hexa CAN0'
    assert plan['can0']['driver'] == 'gs_usb'
    assert plan['can0']['modules'] == ['can', 'can_raw', 'gs_usb']
    assert ['ip', 'link', 'set', 'can0', 'type', 'can', 'bitrate', '125000'] in plan['can0']['commands']
    assert plan['can1']['driver'] == 'gs_usb'
    assert plan['can2']['driver'] == 'gs_usb'


def test_sim_exposes_bom_rmc_sensor_stack_from_config():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    sensors = agent.rmc_sensor_stack

    assert set(sensors) >= {'aht21', 'ens160', 'bh1750', 'rcwl_0516', 'mcp2515_tja1050'}
    assert sensors['aht21']['address'] == '0x38'
    assert sensors['ens160']['address'] == '0x52'
    assert sensors['bh1750']['address'] == '0x23'
    assert sensors['rcwl_0516']['pin'] == 'D3'
    assert sensors['mcp2515_tja1050']['cs_pin'] == 'D10'


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
    assert result['can']['can0']['modules'] == ['can', 'can_raw', 'gs_usb']
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
    assert decoded['sensor_ok'] == {
        'bh1750': True,
        'aht21': True,
        'ens160': True,
        'can': True,
        'rcwl_0516': True,
    }
    assert decoded['sensor_faults'] == []


def test_rmc_fault_frames_name_supported_sensors():
    decoded = common_can.decode_rmc_frame(0x300, [0x07, 0, 3, 1])

    assert decoded['kind'] == 'fault'
    assert decoded['faults'] == ['bh1750', 'aht21', 'ens160']


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
    assert agent.rmc_nodes['2']['aqi'] == 1
    assert agent.rmc_nodes['2']['sensor_ok']['ens160'] is True
