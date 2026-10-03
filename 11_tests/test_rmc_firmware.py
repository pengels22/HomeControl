from importlib import import_module

import pytest

rmc_fw = import_module('07_servises.common.rmc_firmware')
sim = import_module('02_SIM.main')


def test_rmc_firmware_package_validation_rejects_wrong_target():
    package = rmc_fw.make_package(image=b'abc123', firmware_version='1.2.3')
    package['target_module'] = 'LCM'

    with pytest.raises(rmc_fw.FirmwarePackageError):
        rmc_fw.validate_package(package, compatible_hardware=['RMC-NANO-ATMEGA328P'])


def test_rmc_firmware_frame_plan_uses_classical_can_payloads_and_target_node():
    image = bytes(range(10))
    package = rmc_fw.make_package(image=image, firmware_version='1.2.3', session_id='session-1')

    frames = rmc_fw.update_frame_plan(image, node_id=7, session_id=package['session_id'])
    data_frames = [frame for frame in frames if frame['command'] == 'UPDATE_DATA']

    assert frames[0]['command'] == 'UPDATE_ENTER_BOOTLOADER'
    assert frames[0]['arbitration_id'] == 0x670
    assert data_frames[0]['data'][0] == rmc_fw.RMC_FIRMWARE_COMMANDS['UPDATE_DATA']
    assert data_frames[0]['data'][2:4] == [0, 0]
    assert data_frames[1]['data'][2:4] == [0, 1]
    assert all(len(frame['data']) == 8 for frame in frames)
    assert len(data_frames) == 3
    assert frames[-1]['command'] == 'UPDATE_REBOOT'


@pytest.mark.asyncio
async def test_sim_stages_and_completes_rmc_firmware_update(tmp_path):
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    cfg['rmc_firmware_updates']['staging_root'] = str(tmp_path)
    agent = sim.SIMAgent(cfg)
    image = bytes((i % 251 for i in range(64)))
    package = rmc_fw.make_package(image=image, firmware_version='1.4.0', session_id='test-session')

    result = await agent.apply_command({
        'op': 'rmc_firmware_update',
        'target': {'rmc_id': 'RMC-07', 'node_id': 7, 'can_interface': 'can0'},
        'package': package,
    })

    assert result['ok'] is True
    assert result['session']['state'] == 'COMPLETE'
    assert result['session']['progress_pct'] == 100
    assert result['reported_firmware_version'] == '1.4.0'
    assert agent.rmc_nodes['7']['firmware_version'] == '1.4.0'
    assert agent.can_network.snapshot()['can0']['tx_count'] > 0
    assert not (tmp_path / 'test-session.bin').exists()


@pytest.mark.asyncio
async def test_sim_rejects_incompatible_rmc_firmware(tmp_path):
    cfg = sim.common_cfg.load_yaml(sim.Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    cfg['rmc_firmware_updates']['staging_root'] = str(tmp_path)
    agent = sim.SIMAgent(cfg)
    package = rmc_fw.make_package(
        image=b'bad-hardware',
        firmware_version='1.4.0',
        hardware_revision='OTHER-HARDWARE',
    )

    result = await agent.apply_command({
        'op': 'rmc_firmware_update',
        'target': {'rmc_id': 'RMC-07', 'node_id': 7, 'can_interface': 'can0'},
        'package': package,
    })

    assert result['ok'] is False
    assert result['session']['state'] == 'FAILED'
    assert 'incompatible RMC hardware revision' in result['error']
