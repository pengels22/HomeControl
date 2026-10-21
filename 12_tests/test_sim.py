from importlib import import_module
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sim = import_module('02_SIM.main')
common_can = import_module('08_servises.common.can')
common_agent = import_module('08_servises.common.agent')


def simulated_config():
    config = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '07_config/02_SIM/sim.yaml')
    config['io'] = {'mode': 'simulated'}
    return config


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
async def test_module_agent_reports_to_local_heartbeat_v3_socket(tmp_path):
    received = []
    short_dir = Path(tempfile.mkdtemp(prefix='hcm-', dir='/tmp'))
    sock = short_dir / 'hb.sock'

    async def handle(reader, writer):
        received.append(json.loads((await reader.readline()).decode('utf-8')))
        writer.write(b'{"ok": true}\\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await sim.asyncio.start_unix_server(handle, path=str(sock))
    try:
        agent = common_agent.ModuleAgent('SIM', {
            'identity_path': str(tmp_path / 'identity.json'),
            'heartbeat_v3': {'socket_path': str(sock), 'watchdog_name': 'sim_app'},
        })
        await agent.heartbeat_status('sim_app', 'running')
        await agent.heartbeat_fault('sim_fault', 'offline')
        await agent.heartbeat_pulse()
    finally:
        server.close()
        await server.wait_closed()
        shutil.rmtree(str(short_dir), ignore_errors=True)

    assert received == [
        {'action': 'status_set', 'name': 'sim_app', 'value': 'running'},
        {'action': 'fault_set', 'name': 'sim_fault', 'value': 'offline'},
        {'action': 'pulse', 'name': 'sim_app'},
    ]


@pytest.mark.asyncio
async def test_sim_mock_can_receiver_decodes_and_attributes_frames():
    transport = common_can.MockCANTransport()
    agent = sim.SIMAgent({
        'can_enabled': True,
        'can_interfaces': [{'name': 'can0', 'label': 'CAN A', 'enabled': True}],
        'can_transports': {'can0': transport},
    })
    arbitration_id, data = common_can.encode_rmc_telemetry(
        3, presence=True, temperature_c=21, humidity_pct=45, lux=300, aqi=1,
    )
    await agent.start_can_receivers()
    try:
        await transport.inject(arbitration_id, data)
        for _ in range(20):
            if '3' in agent.rmc_nodes:
                break
            await sim.asyncio.sleep(0.01)
        state = await agent.collect_state()
    finally:
        await agent.stop_can_receivers()

    assert state['rmc_nodes']['3']['can_interface'] == 'can0'
    assert state['rmc_nodes']['3']['online'] is True
    assert state['can_receiver']['interfaces'] == ['can0']
    assert transport.started is False
    assert agent.active_can_transports == {}


@pytest.mark.asyncio
async def test_sim_can_partial_start_failure_closes_started_transports():
    first = common_can.MockCANTransport()

    class FailingTransport(common_can.MockCANTransport):
        async def start(self):
            raise RuntimeError('bind failed')

    agent = sim.SIMAgent({
        'can_enabled': True,
        'can_interfaces': [
            {'name': 'can0', 'enabled': True},
            {'name': 'can1', 'enabled': True},
        ],
        'can_transports': {'can0': first, 'can1': FailingTransport()},
    })
    with pytest.raises(RuntimeError, match='can1'):
        await agent.start_can_receivers()
    assert first.started is False
    assert agent.active_can_transports == {}
    assert agent.can_receive_tasks == {}


@pytest.mark.asyncio
async def test_sim_physical_firmware_update_fails_closed_without_bootloader_transport():
    agent = sim.SIMAgent({'io_mode': 'real', 'can_interfaces': [{'name': 'can0', 'enabled': True}]})
    result = await agent.perform_rmc_firmware_update({'package': {'session_id': 'test'}})

    assert result == {
        'ok': False,
        'error': 'physical_rmc_bootloader_transport_not_implemented',
        'simulation': False,
        'physical_commands_sent': False,
    }


@pytest.mark.asyncio
async def test_real_sim_reports_explicitly_unavailable_can_without_probing_host():
    agent = sim.SIMAgent({
        'io': {'mode': 'real'},
        'can_interfaces': [{'name': 'can0', 'enabled': True}],
        'can_transports': {'can0': None},
    })

    await agent.start_can_receivers()
    state = await agent.collect_state()

    assert state['can_receiver']['interfaces'] == []
    assert state['can_receiver']['faults']['can0'] == 'configured transport is unavailable'


def test_sim_can_setup_plan_loads_gs_usb_for_hexa_board():
    cfg = simulated_config()

    plan = common_can.configure_sync(cfg, apply=False)

    assert plan['can0']['hardware'] == 'FYSETC Hexa CAN0'
    assert plan['can0']['driver'] == 'gs_usb'
    assert plan['can0']['modules'] == ['can', 'can_raw', 'gs_usb']
    assert ['ip', 'link', 'set', 'can0', 'type', 'can', 'bitrate', '125000'] in plan['can0']['commands']
    assert plan['can1']['driver'] == 'gs_usb'
    assert plan['can2']['driver'] == 'gs_usb'


def test_sim_exposes_bom_rmc_sensor_stack_from_config():
    cfg = simulated_config()
    agent = sim.SIMAgent(cfg)

    sensors = agent.rmc_sensor_stack

    assert set(sensors) >= {'aht21', 'ens160', 'bh1750', 'rcwl_0516', 'mcp2515_tja1050'}
    assert sensors['aht21']['address'] == '0x38'
    assert sensors['ens160']['address'] == '0x52'
    assert sensors['bh1750']['address'] == '0x23'
    assert sensors['rcwl_0516']['pin'] == 'D3'
    assert sensors['mcp2515_tja1050']['cs_pin'] == 'D10'


@pytest.mark.asyncio
async def test_real_sim_mode_does_not_publish_simulated_measurements():
    cfg = simulated_config()
    cfg['io'] = {'mode': 'real'}
    agent = sim.SIMAgent(cfg)
    state = await agent.collect_state()
    hexa = state['hexa_board']
    assert hexa['aio']['bus_monitors']['bus_3v3']['value'] is None
    assert hexa['aio']['bus_monitors']['bus_3v3']['status'] == 'UNAVAILABLE'
    assert hexa['dio']['dio1']['value'] is None
    result = await agent.apply_command({'op': 'set_hexa_12v', 'channel': 'sw1', 'value': True})
    assert result['ok'] is False
    assert result['error'] == 'physical_12v_adapter_not_implemented'


@pytest.mark.asyncio
async def test_sim_exposes_hexa_board_capabilities_and_adc_bus_monitors():
    cfg = simulated_config()
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
    cfg = simulated_config()
    agent = sim.SIMAgent(cfg)

    dio_result = await agent.apply_command({'op': 'set_hexa_dio', 'channel': 'dio3', 'value': True})
    switch_result = await agent.apply_command({'op': 'set_hexa_12v', 'channel': 'sw1', 'value': True})
    state = await agent.collect_state()

    assert dio_result['ok'] is True
    assert dio_result['channel'] == 'dio3'
    assert dio_result['value'] is True
    assert dio_result['arbitration']['effective_state']['energized'] is True
    assert switch_result['ok'] is True
    assert switch_result['channel'] == 'sw1'
    assert switch_result['value'] is True
    assert state['hexa_board']['dio']['dio3']['value'] is True
    assert state['hexa_board']['switching_12v']['sw1']['value'] is True


@pytest.mark.asyncio
async def test_sim_can_restart_12v_loop_power_switch():
    cfg = simulated_config()
    agent = sim.SIMAgent(cfg)

    result = await agent.apply_command({'op': 'restart_hexa_12v', 'channel': 'sw2', 'delay_s': 0})
    state = await agent.collect_state()

    assert result['ok'] is True
    assert result['channel'] == 'sw2'
    assert result['value'] is True
    assert result['restarted'] is True
    assert result['power_off_s'] == 0.0
    assert result['arbitration']['effective_state']['energized'] is True
    assert state['hexa_board']['switching_12v']['sw2']['label'] == 'Loop B power'
    assert state['hexa_board']['switching_12v']['sw2']['value'] is True


@pytest.mark.asyncio
async def test_sim_restart_uses_global_default_delay(monkeypatch):
    base = sim.common_global_config.load_global_config('SIM').as_dict()
    base['Hexa_12V_Restart_Off_Time'] = 10
    monkeypatch.setattr(sim.common_global_config, 'load_global_config', lambda component: SimpleNamespace(**base))
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '07_config/02_SIM/sim.yaml')
    agent = sim.SIMAgent(cfg)

    started = sim.time.time()
    result = await agent.apply_command({'op': 'restart_hexa_12v', 'channel': 'sw2'})

    assert result['power_off_s'] == 0.01
    assert sim.time.time() - started >= 0.009


@pytest.mark.asyncio
async def test_sim_can_link_and_disconnect_hexa_usb_device_by_id():
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '07_config/02_SIM/sim.yaml')
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
