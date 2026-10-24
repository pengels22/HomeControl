from importlib import import_module

import pytest

rmc_fw = import_module('08_servises.common.rmc_firmware')


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


def test_rmc_build_time_config_uses_global_values():
    cfg = rmc_fw.build_time_config()

    assert cfg['CAN_BITRATE'] == 125000
    assert cfg['RMC_FIRMWARE_BLOCK_SIZE'] == 4
    assert cfg['TELEMETRY_INTERVAL_MS'] == 5000
