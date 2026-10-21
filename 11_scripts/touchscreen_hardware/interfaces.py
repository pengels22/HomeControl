from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DisplayConfig:
    width: int = 480
    height: int = 320
    rotation: int = 90
    spi_device: str = "/dev/spidev1.1"
    spi_speed_hz: int = 10_000_000
    dc_gpio_chip: str = "/dev/gpiochip1"
    dc_gpio_line: int = 70
    reset_gpio_chip: str | None = None
    reset_gpio_line: int | None = None
    backlight_gpio_chip: str | None = None
    backlight_gpio_line: int | None = None


@dataclass(frozen=True)
class TouchConfig:
    controller: str = "FT6336U"
    i2c_bus: int = 2
    i2c_device: str = "/dev/i2c-2"
    i2c_address: int = 0x38
    width: int = 480
    height: int = 320
    rotation: int = 90
    reset_gpio_chip: str = "/dev/gpiochip1"
    reset_gpio_line: int = 69


@dataclass(frozen=True)
class TouchPoint:
    id: int
    x: int
    y: int


@dataclass(frozen=True)
class TouchEvent:
    kind: str
    points: tuple[TouchPoint, ...]


def validate_display_config(config: DisplayConfig) -> None:
    if (config.width, config.height) != (480, 320):
        raise ValueError("validated Orange Pi touchscreen resolution is 480x320")
    if config.rotation not in {0, 90, 180, 270}:
        raise ValueError("display rotation must be one of 0, 90, 180, 270")
    if config.spi_device != "/dev/spidev1.1":
        raise ValueError("Orange Pi display must use /dev/spidev1.1")
    if config.spi_speed_hz > 10_000_000:
        raise ValueError("validated ST7796 SPI speed must not exceed 10 MHz")
    if (config.dc_gpio_chip, config.dc_gpio_line) != ("/dev/gpiochip1", 70):
        raise ValueError("validated LCD D/C is gpiochip1 line 70")
    if config.reset_gpio_line is not None:
        raise ValueError("LCD reset is software-disabled on the validated kernel")


def validate_touch_config(config: TouchConfig) -> None:
    if config.controller.upper() != "FT6336U":
        raise ValueError("validated touchscreen controller is FT6336U")
    if config.i2c_bus != 2 or config.i2c_device != "/dev/i2c-2" or config.i2c_address != 0x38:
        raise ValueError("validated FT6336U bus is /dev/i2c-2 at 0x38")
    if (config.width, config.height) != (480, 320):
        raise ValueError("validated touchscreen resolution is 480x320")
    if (config.reset_gpio_chip, config.reset_gpio_line) != ("/dev/gpiochip1", 69):
        raise ValueError("validated touch reset is gpiochip1 line 69")
