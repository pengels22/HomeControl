from importlib import import_module


gpio_inputs = import_module('00_Heartbeat.gpio_inputs')


def test_conflict_gpio_monitor_is_unknown_when_disabled():
    monitor = gpio_inputs.GPIOInputMonitor({
        'enabled': False,
        'debounce_ms': 250,
        'fire_alarm_s': {'gpiochip': '/dev/gpiochip1', 'line': 260, 'active_level': 1},
        'fire_alarm_P': {'gpiochip': '/dev/gpiochip1', 'line': 259, 'active_level': 1},
    })
    assert monitor.read() == {
        'fire_alarm_s': {'state': 'unknown', 'health': 'disabled'},
        'fire_alarm_P': {'state': 'unknown', 'health': 'disabled'},
    }


def test_debounced_level_requires_250ms():
    level = gpio_inputs.DebouncedLevel(250)
    assert level.update(False, 0.0) is None
    assert level.update(False, 0.249) is None
    assert level.update(False, 0.25) is False
    assert level.update(True, 1.0) is False
    assert level.update(True, 1.249) is False
    assert level.update(True, 1.25) is True
