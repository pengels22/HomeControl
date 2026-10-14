from importlib import import_module

import pytest


infra = import_module('07_servises.common.module_infra')


def test_hardware_constants_match_verified_addresses_and_rcm_map():
    assert infra.I2C_COMPONENTS['relay_card_1']['address'] == 0x20
    assert infra.I2C_COMPONENTS['relay_card_2']['address'] == 0x21
    assert infra.I2C_COMPONENTS['mcp1']['address'] == 0x26
    assert infra.I2C_COMPONENTS['mcp2']['address'] == 0x27
    assert infra.RCM_RELAY_MAP['A1'] == ('relay_card_1', 0)
    assert infra.RCM_RELAY_MAP['B8'] == ('relay_card_1', 15)
    assert infra.RCM_RELAY_MAP['C1'] == ('relay_card_2', 0)
    assert infra.RCM_RELAY_MAP['D8'] == ('relay_card_2', 15)


def test_lcm_default_inventory_is_8_10_4_with_real_outputs_disabled():
    cfg = infra.default_lcm_config()

    assert [item['channel'] for item in cfg['relays']] == [f'A{i}' for i in range(1, 9)]
    assert [item['channel'] for item in cfg['analog_dimmers']] == [f'10-{i}' for i in range(1, 11)]
    assert [item['channel'] for item in cfg['hv_dimmers']] == [f'HV-{i}' for i in range(1, 5)]
    assert cfg['hardware']['analog_pwm']['real_output_enabled'] is False
    assert cfg['hardware']['shelly']['real_output_enabled'] is False


def test_rcm_csv_schema_and_channel_count_are_strict(tmp_path):
    store = infra.LocalConfigStore(tmp_path, 'RCM', 'RCM_2')
    result = store.save_rcm_csv(infra.default_rcm_config())

    text = (tmp_path / 'config' / 'RCM' / 'RCM_2.csv').read_text()
    assert text.splitlines()[0] == 'Channel ID,Name,on,Lockout'
    assert len(text.splitlines()) == 33
    assert result['channel_count'] == 32
    with pytest.raises(ValueError):
        store.save_rcm_csv(infra.default_rcm_config()[:-1])


def test_rcm_csv_round_trip_preserves_32_channels(tmp_path):
    store = infra.LocalConfigStore(tmp_path, 'RCM', 'RCM2')
    channels = infra.default_rcm_config()
    channels[0]['name'] = 'Kitchen'
    channels[0]['on'] = True
    channels[0]['lockout'] = True

    store.save_rcm_csv(channels)
    loaded = store.load_rcm_csv()

    assert len(loaded) == 32
    assert loaded[0] == {'channel': 'A1', 'name': 'Kitchen', 'on': True, 'lockout': True}
    assert loaded[-1]['channel'] == 'D8'


def test_lcm_csv_round_trip_preserves_22_channel_inventory(tmp_path):
    store = infra.LocalConfigStore(tmp_path, 'LCM', 'LCM1')
    channels = infra.default_lcm_channels()
    channels[0]['name'] = 'Relay One'
    dimmer = next(item for item in channels if item['channel'] == '10-10')
    dimmer.update({'name': 'Cove', 'lockout': True, 'emergency_lighting': True, 'max_intensity': 72, 'fade_seconds': 4.5})
    hv = next(item for item in channels if item['channel'] == 'HV-4')
    hv['name'] = 'Pendant'

    result = store.save_lcm_csv(channels)
    loaded = store.load_lcm_csv()

    assert result['channel_count'] == 22
    assert [item['channel'] for item in loaded[:8]] == [f'A{i}' for i in range(1, 9)]
    assert [item['channel'] for item in loaded[8:18]] == [f'10-{i}' for i in range(1, 11)]
    assert [item['channel'] for item in loaded[18:]] == [f'HV-{i}' for i in range(1, 5)]
    assert next(item for item in loaded if item['channel'] == '10-10')['max_intensity'] == 72
    assert next(item for item in loaded if item['channel'] == '10-10')['lockout'] is True


def test_structured_event_logger_suppresses_duplicates_until_recovery(tmp_path):
    logger = infra.StructuredEventLogger('RCM1', tmp_path)

    records = [
        logger.log(component='relay_card_1', category='i2c', severity='error', code='i2c_write_failed', message='write failed')
        for _ in range(4)
    ]
    assert records[0] is not None
    assert records[1] is not None
    assert records[2] is not None
    assert 'suppressed' in records[2]['message']
    assert records[3] is None

    recovered = logger.log(component='relay_card_1', category='i2c', severity='recovered', code='i2c_write_failed', message='bus recovered')
    next_failure = logger.log(component='relay_card_1', category='i2c', severity='error', code='i2c_write_failed', message='write failed again')
    assert recovered is not None
    assert next_failure is not None


def test_offline_event_queue_is_idempotent(tmp_path):
    queue = infra.OfflineEventQueue(tmp_path / 'pending.json')
    event = {'event_id': 'evt-1', 'message': 'stored while offline'}

    queue.enqueue(event)
    queue.enqueue(event)
    assert queue.count() == 1
    assert queue.batch() == [event]

    queue.mark_delivered(['evt-1'])
    assert queue.count() == 0


def test_bank_selection_requires_exactly_one_mcp2_bit():
    assert infra.selected_bank_from_mcp2(0b0001) == 1
    assert infra.selected_bank_from_mcp2(0b1000) == 4
    with pytest.raises(ValueError):
        infra.selected_bank_from_mcp2(0)
    with pytest.raises(ValueError):
        infra.selected_bank_from_mcp2(0b0011)


def test_led_state_fault_and_hcm_internet_rules():
    normal = infra.compute_led_state(initialized=True, heartbeat_ack_current=True, active_faults=[])
    assert normal == {'POWER': True, 'LINK': True, 'STATUS': True, 'FAULT': False}

    hcm_no_internet = infra.compute_led_state(initialized=True, heartbeat_ack_current=True, active_faults=[], internet_ok=False, is_hcm=True)
    assert hcm_no_internet['STATUS'] is False
    assert hcm_no_internet['FAULT'] is True
