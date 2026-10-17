"""Validated loading for the processor-specific fire input manifest entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_yaml


SENSOR_NAMES = ("fire_alarm_s", "fire_alarm_P")


class FireAlarmConfigError(ValueError):
    pass


def load_fire_alarm_signals(path: str | Path) -> dict[str, dict[str, Any]]:
    data = load_yaml(path)
    signals = data.get("signals")
    if not isinstance(signals, dict):
        raise FireAlarmConfigError(f"{path} missing signals mapping")
    result = {}
    for name in SENSOR_NAMES:
        entry = signals.get(name)
        if not isinstance(entry, dict):
            raise FireAlarmConfigError(f"{path} missing {name} signal")
        required = ("physical_pin", "gpiochip", "line", "normal_level", "alarm_level", "debounce_ms", "wiring")
        missing = [key for key in required if key not in entry]
        if missing:
            raise FireAlarmConfigError(f"{path} {name} missing {', '.join(missing)}")
        if str(entry["normal_level"]).lower() != "low" or str(entry["alarm_level"]).lower() != "high":
            raise FireAlarmConfigError(f"{path} {name} must define LOW normal and HIGH alarm")
        if int(entry["debounce_ms"]) != 250:
            raise FireAlarmConfigError(f"{path} {name} must use 250 ms debounce")
        wiring = entry["wiring"]
        if wiring != {"no": "3.3V", "nc": "GND", "com": "GPIO"}:
            raise FireAlarmConfigError(f"{path} {name} has unsupported SPDT wiring convention")
        result[name] = dict(entry)
    return result
