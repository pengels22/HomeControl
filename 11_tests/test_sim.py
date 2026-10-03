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
async def test_sim_exposes_hexa_board_capabilities_and_adc_bus_monitors():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    state = await agent.collect_state()
    hexa = state['hexa_board']

    assert set(hexa) >= {'aio', 'dio', 'usb', 'can', 'switching_12v'}
    assert hexa['aio']['ads1115'][0]['address'] == '0x48'
    assert hexa['aio']['ads1115'][1]['address'] == '0x49'
    assert hexa['aio']['ads1115'][2]['address'] == '0x4A'
    assert hexa['aio']['bus_monitors']['bus_3v3']['status'] == 'OK'
    assert hexa['aio']['bus_monitors']['bus_5v']['status'] == 'OK'
    assert hexa['aio']['loop_monitors']['loop_a']['status'] == 'OK'
    assert hexa['aio']['loop_monitors']['loop_b']['status'] == 'OK'
    assert hexa['aio']['loop_monitors']['loop_c']['status'] == 'OFF'
    assert hexa['aio']['loop_monitors']['loop_d']['visible'] is False
    assert list(hexa['aio']['analog_inputs']) == ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8']
    assert hexa['aio']['analog_inputs']['a1']['label'] == 'A1'
    assert hexa['aio']['analog_inputs']['a8']['source'] == 'ADS 0x49 CH3'
    assert hexa['all_bus_monitors_ok'] is True
    assert hexa['usb']['available_ports'][1]['label'] == 'UCAN loop B'
    assert hexa['usb']['linked_devices'] == []
    assert set(hexa['switching_12v']) == {'sw1', 'sw2', 'sw3'}


@pytest.mark.asyncio
async def test_sim_can_toggle_hexa_dio_and_12v_switch_outputs():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    dio_result = await agent.apply_command({'op': 'set_hexa_dio', 'channel': 'dio3', 'value': True})
    switch_result = await agent.apply_command({'op': 'set_hexa_12v', 'channel': 'sw1', 'value': True})
    state = await agent.collect_state()

    assert dio_result == {'ok': True, 'channel': 'dio3', 'value': True}
    assert switch_result == {'ok': True, 'channel': 'sw1', 'value': True}
    assert state['hexa_board']['dio']['dio3']['value'] is True
    assert state['hexa_board']['switching_12v']['sw1']['value'] is True


@pytest.mark.asyncio
async def test_sim_can_restart_12v_loop_power_switch():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    result = await agent.apply_command({'op': 'restart_hexa_12v', 'channel': 'sw2', 'delay_s': 0})
    state = await agent.collect_state()

    assert result == {'ok': True, 'channel': 'sw2', 'value': True, 'restarted': True}
    assert state['hexa_board']['switching_12v']['sw2']['label'] == 'Loop B power'
    assert state['hexa_board']['switching_12v']['sw2']['value'] is True


@pytest.mark.asyncio
async def test_sim_can_link_and_disconnect_hexa_usb_device_by_id():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    linked = await agent.apply_command({'op': 'link_hexa_usb', 'name': 'UCAN B', 'port': 'usb2'})
    state = await agent.collect_state()
    link_id = linked['link']['id']

    assert linked['ok'] is True
    assert state['hexa_board']['usb']['linked_devices'][0]['id'] == link_id
    assert [p['id'] for p in state['hexa_board']['usb']['available_ports']] == ['usb1', 'usb3']

    disconnected = await agent.apply_command({'op': 'disconnect_hexa_usb', 'id': link_id})
    state = await agent.collect_state()

    assert disconnected['ok'] is True
    assert state['hexa_board']['usb']['linked_devices'] == []
    assert [p['id'] for p in state['hexa_board']['usb']['available_ports']] == ['usb1', 'usb2', 'usb3']


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
