from __future__ import annotations

from dataclasses import dataclass

from .ft6336_touch import FT6336Touch
from .interfaces import DisplayConfig, TouchConfig
from .st7796_display import ST7796Display


@dataclass(frozen=True)
class TouchscreenHardwareService:
    """Selectable hardware boundary; it never controls module outputs."""

    role: str
    mode: str = "simulated"
    display_config: DisplayConfig = DisplayConfig()
    touch_config: TouchConfig = TouchConfig()

    def create_display(self):
        if self.mode == "simulated": return None
        if self.mode != "orange_pi": raise ValueError("unsupported touchscreen hardware mode")
        return ST7796Display(self.display_config)

    def create_touch(self):
        if self.mode == "simulated": return None
        if self.mode != "orange_pi": raise ValueError("unsupported touchscreen hardware mode")
        return FT6336Touch(self.touch_config)


def create_service(role: str, mode: str = "simulated") -> TouchscreenHardwareService:
    role = role.upper()
    if role not in {"RCM", "LCM"}:
        raise ValueError("Orange Pi touchscreen service supports RCM and LCM")
    if mode not in {"simulated", "orange_pi"}:
        raise ValueError("mode must be simulated or orange_pi")
    return TouchscreenHardwareService(role=role, mode=mode)
