from importlib import import_module
from pathlib import Path


config = import_module('07_servises.common.fire_alarm_config')

ROOT = Path(__file__).resolve().parents[1]


def test_hcm_manifest_contains_authoritative_fire_input_mappings():
    signals = config.load_fire_alarm_signals(ROOT / '06_config/01_HCM/hardware_pins.yaml')
    assert signals['fire_alarm_s']['physical_pin'] == 38
    assert signals['fire_alarm_s']['gpiochip'] == '/dev/gpiochip0'
    assert signals['fire_alarm_s']['line'] == 159
    assert signals['fire_alarm_P']['physical_pin'] == 40
    assert signals['fire_alarm_P']['gpiochip'] == '/dev/gpiochip0'
    assert signals['fire_alarm_P']['line'] == 158


def test_conflict_manifest_contains_independent_processor_mappings():
    signals = config.load_fire_alarm_signals(ROOT / '06_config/07_CONFLICT/hardware_pins.yaml')
    assert signals['fire_alarm_s']['soc_gpio'] == 'PI4'
    assert signals['fire_alarm_s']['soc_gpio_number'] == 260
    assert signals['fire_alarm_s']['gpiochip'] == '/dev/gpiochip1'
    assert signals['fire_alarm_s']['line'] == 260
    assert signals['fire_alarm_P']['soc_gpio'] == 'PI3'
    assert signals['fire_alarm_P']['soc_gpio_number'] == 259
    assert signals['fire_alarm_P']['line'] == 259
