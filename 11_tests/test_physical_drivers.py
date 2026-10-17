from importlib import import_module

import pytest


drivers = import_module('07_servises.common.physical_drivers')


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


def test_shelly_mock_and_debounce_are_deterministic():
    shelly = drivers.MockShellyTransport()
    assert shelly.set_brightness('light:0', 65)['percent'] == 65
    debounce = drivers.DebouncedInput(debounce_ms=50)
    assert debounce.update(1, now=1.0) is None
    assert debounce.update(1, now=1.02) is None
    assert debounce.update(1, now=1.06) == 1


def test_lab1_bundle_contains_production_classes_and_only_mock_transports():
    bundle = drivers.build_lab1_mock_drivers()
    assert isinstance(bundle['rcm_relays'], drivers.XL9535RelayDriver)
    assert isinstance(bundle['lcm_relays'], drivers.MCP23017RelayDriver)
    assert isinstance(bundle['lcm_pwm'], drivers.PCA9685Driver)
    assert isinstance(bundle['i2c_transport'], drivers.MockI2CTransport)
    assert bundle['i2c_transport'].operations == []
