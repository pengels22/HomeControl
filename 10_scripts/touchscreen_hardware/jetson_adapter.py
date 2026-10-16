from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JetsonTouchscreenAdapterConfig:
    """Future HCM adapter contract; Jetson mappings are intentionally explicit."""

    spi_device: str = "/dev/spidev0.0"
    i2c_device: str = "/dev/i2c-0"
    display_dc_physical_pin: int = 22
    display_reset_physical_pin: int = 18
    touch_sda_physical_pin: int = 27
    touch_scl_physical_pin: int = 28
    fire_input_physical_pin: int = 38
    ac_present_physical_pin: int = 40


def create_jetson_adapter_config() -> JetsonTouchscreenAdapterConfig:
    """Return configuration only; no Jetson device nodes are opened."""
    return JetsonTouchscreenAdapterConfig()
