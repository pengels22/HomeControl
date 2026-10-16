from __future__ import annotations

import asyncio
import logging

from .interfaces import TouchConfig, TouchEvent, TouchPoint, validate_touch_config

LOGGER = logging.getLogger(__name__)


class FT6336Touch:
    """Polled FT6336U adapter imported from the validated Travel_Laser driver."""

    def __init__(self, config: TouchConfig, poll_interval: float = 0.03) -> None:
        validate_touch_config(config)
        self.config = config
        self.poll_interval = poll_interval
        self._bus = None
        self._reset_request = None
        self._was_down = False
        self._read_failures = 0

    async def initialize(self) -> None:
        await self._hardware_reset(); self._open_bus(); await asyncio.sleep(0)

    async def read_event(self) -> TouchEvent | None:
        await asyncio.sleep(self.poll_interval)
        if self._bus is None:
            await self._recover_bus(); return None
        try:
            data = self._bus.read_i2c_block_data(self.config.i2c_address, 0x02, 11)
        except OSError as exc:
            self._read_failures += 1; self._was_down = False
            if self._read_failures in {1, 10, 100}: LOGGER.warning("FT6336 read failed on i2c-%s: %s", self.config.i2c_bus, exc)
            await self._recover_bus(); return None
        self._read_failures = 0; count = data[0] & 0x0F
        if count == 0:
            if self._was_down: self._was_down = False; return TouchEvent("up", ())
            return None
        raw_x = ((data[1] & 0x0F) << 8) | data[2]; raw_y = ((data[3] & 0x0F) << 8) | data[4]
        x, y = self._transform(raw_x, raw_y); kind = "move" if self._was_down else "down"; self._was_down = True
        return TouchEvent(kind, (TouchPoint(0, x, y),))

    async def close(self) -> None:
        if self._bus is not None: self._bus.close(); self._bus = None
        if self._reset_request is not None: self._reset_request.release(); self._reset_request = None

    def _open_bus(self) -> None:
        try:
            from smbus2 import SMBus
        except ImportError:
            from smbus import SMBus
        self._bus = SMBus(self.config.i2c_bus)

    async def _recover_bus(self) -> None:
        if self._bus is not None: self._bus.close(); self._bus = None
        await asyncio.sleep(0.10)
        try: self._open_bus()
        except OSError as exc:
            if self._read_failures in {1, 10, 100}: LOGGER.warning("FT6336 bus reopen failed: %s", exc)

    async def _hardware_reset(self) -> None:
        import gpiod
        from gpiod.line import Direction, Value
        self._reset_request = gpiod.request_lines(self.config.reset_gpio_chip, consumer="homecontrol-touch-reset", config={self.config.reset_gpio_line: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
        self._reset_request.set_value(self.config.reset_gpio_line, Value.ACTIVE); await asyncio.sleep(0.05)
        self._reset_request.set_value(self.config.reset_gpio_line, Value.INACTIVE); await asyncio.sleep(0.02)
        self._reset_request.set_value(self.config.reset_gpio_line, Value.ACTIVE); await asyncio.sleep(0.30)

    def _transform(self, raw_x: int, raw_y: int) -> tuple[int, int]:
        if self.config.rotation == 90: x, y = raw_y, self.config.height - 1 - raw_x
        elif self.config.rotation == 270: x, y = self.config.width - 1 - raw_y, raw_x
        elif self.config.rotation == 180: x, y = self.config.width - 1 - raw_x, self.config.height - 1 - raw_y
        else: x, y = raw_x, raw_y
        return max(0, min(self.config.width - 1, x)), max(0, min(self.config.height - 1, y))
