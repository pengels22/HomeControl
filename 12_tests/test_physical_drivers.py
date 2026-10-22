from importlib import import_module

import pytest


drivers = import_module('08_servises.common.physical_drivers')
factory = import_module('08_servises.common.hardware_factory')


def test_xl9535_initializes_safe_and_preserves_other_bits():
    transport = drivers.MockI2CTransport()
    driver = drivers.XL9535RelayDriver(drivers.LockedI2C(transport))
    assert driver.initialize()['safe_state'] == 'all_off'
    first = driver.set_channel(0, True)
    assert first['readback'] is True
    assert driver.read_channel(1) is False
    writes = [op for op in transport.operations if op['op'] == 'write']
    assert any(op['address'] == 0x20 and op['register'] == 0x02 for op in writes)


def test_xl9535_maps_second_board_and_rejects_out_of_range():
    transport = drivers.MockI2CTransport()
    driver = drivers.XL9535RelayDriver(drivers.LockedI2C(transport))
    driver.initialize()
    driver.set_channel(16, True)
    assert any(op['address'] == 0x21 for op in transport.operations)
    with pytest.raises(ValueError):
        driver.set_channel(32, True)


def test_mcp23017_and_pca9685_use_mock_transactions():
    transport = drivers.MockI2CTransport()
    bus = drivers.LockedI2C(transport)
    relay = drivers.MCP23017RelayDriver(bus, 0x27)
    pwm = drivers.PCA9685Driver(bus)
    relay.initialize()
    pwm.initialize()
    assert relay.set_channel(2, True)['readback'] is True
    assert pwm.set_percent(9, 65)['raw'] == round(65 * 4095 / 100)
    assert any(op['address'] == 0x27 for op in transport.operations)
    assert any(op['address'] == 0x40 for op in transport.operations)


def test_mcp23017_uses_port_b_and_does_not_touch_port_a():
    transport = drivers.MockI2CTransport(strict_registers=True, device_registers={
        0x27: {0x00, 0x01, 0x14, 0x15},
    })
    relay = drivers.MCP23017RelayDriver(drivers.LockedI2C(transport), 0x27)
    relay.initialize()
    relay.set_channel(0, True)
    writes = [op for op in transport.operations if op['op'] == 'write']
    assert {op['register'] for op in writes} == {0x01, 0x15}
    assert all(op['register'] not in {0x00, 0x14} for op in writes)


def test_rcm_input_driver_configures_pullups_and_reads_front_panel_ports():
    transport = drivers.MockI2CTransport(strict_registers=True, device_registers={
        0x26: {0x00, 0x01, 0x0C, 0x0D, 0x12, 0x13},
        0x27: {0x00, 0x01, 0x0C, 0x0D, 0x12, 0x13},
    })
    driver = drivers.MCP23017InputDriver(drivers.LockedI2C(transport))
    driver.initialize()
    transport.registers[(0x26, 0x12)] = 0xFE
    transport.registers[(0x26, 0x13)] = 0x7F
    transport.registers[(0x27, 0x12)] = 0xFD
    assert driver.read_ports() == {'mcp1_gpa': 0xFE, 'mcp1_gpb': 0x7F, 'mcp2_gpa': 0xFD}
    writes = [op for op in transport.operations if op['op'] == 'write']
    assert len(writes) == 8
    assert all(op['value'] == 0xFF for op in writes)


def test_pca9685_programs_sleep_wake_and_uses_on_zero_off_raw():
    transport = drivers.MockI2CTransport(strict_registers=True, device_registers={
        0x40: set(range(0x00, 0x10)) | {0xFE},
    })
    pwm = drivers.PCA9685Driver(drivers.LockedI2C(transport), frequency_hz=1000)
    pwm.initialize()
    init = [op for op in transport.operations if op['op'] == 'write']
    assert [op['value'] for op in init if op['register'] == 0x00] == [0x30, 0x20, 0xA0]
    pwm.set_percent(0, 0)
    pwm.set_percent(1, 65)
    writes = [op for op in transport.operations if op['op'] == 'write']
    channel_zero = [op['value'] for op in writes if op['register'] in {0x06, 0x07, 0x08, 0x09}]
    channel_one = [op['value'] for op in writes if op['register'] in {0x0A, 0x0B, 0x0C, 0x0D}]
    assert channel_zero == [0, 0, 0, 0x10]
    assert channel_one[0:2] == [0, 0]
    assert channel_one[2] == round(65 * 4095 / 100) & 0xFF
    assert channel_one[3] == (round(65 * 4095 / 100) >> 8) & 0x0F


def test_shelly_mock_and_debounce_are_deterministic():
    shelly = drivers.MockShellyTransport()
    assert shelly.set_brightness('light:0', 65)['percent'] == 65
    with pytest.raises(drivers.HardwareTransportError):
        shelly.set_brightness('relay:0', 65)
    with pytest.raises(drivers.HardwareTransportError):
        shelly.set_brightness('light:0', float('nan'))
    debounce = drivers.DebouncedInput(debounce_ms=50)
    assert debounce.update(1, now=1.0) is None
    assert debounce.update(1, now=1.02) is None
    assert debounce.update(1, now=1.06) == 1


def test_lab1_bundle_contains_production_classes_and_only_mock_transports():
    bundle = drivers.build_lab1_mock_drivers()
    assert isinstance(bundle['rcm_relays'], drivers.XL9535RelayDriver)
    assert isinstance(bundle['rcm_inputs'], drivers.MCP23017InputDriver)
    assert isinstance(bundle['lcm_relays'], drivers.MCP23017RelayDriver)
    assert isinstance(bundle['lcm_pwm'], drivers.PCA9685Driver)
    assert isinstance(bundle['i2c_transport'], drivers.MockI2CTransport)
    assert bundle['i2c_transport'].operations == []


def test_mock_i2c_retains_bounded_diagnostics_but_counts_all_operations():
    transport = drivers.MockI2CTransport(max_operations=2)
    for index in range(5):
        transport.write_byte_data(0x20, index, index)
    assert len(transport.operations) == 2
    assert transport.operation_count == 5


def test_hardware_factory_keeps_simulated_and_disabled_modes_nonphysical():
    simulated = factory.build_hardware_bundle('RCM', {'hardware_mode': 'simulated'})
    disabled = factory.build_hardware_bundle('LCM', {'hardware_mode': 'disabled'})

    assert simulated.mode == 'simulated'
    assert simulated.transport_type == 'none'
    assert simulated.rcm_relays is None
    assert disabled.mode == 'disabled'
    assert disabled.lcm_pwm is None


def test_hardware_factory_mock_mode_uses_manifest_addresses():
    bundle = factory.build_hardware_bundle(
        'LCM',
        {'hardware_mode': 'mock'},
        {'buses': {'i2c': {'mcp2': {'address': '0x27'}, 'pca9685': {'address': '0x40', 'frequency_hz': 1000}}}},
    )

    assert bundle.mode == 'mock'
    assert bundle.lcm_relays.address == 0x27
    assert bundle.lcm_pwm.address == 0x40
