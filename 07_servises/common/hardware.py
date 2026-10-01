from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DigitalBank:
    names: list[str]
    values: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.values.setdefault(n, False)

    def set(self, channel: str, value: bool) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        self.values[channel] = bool(value)

    def get(self, channel: str) -> bool:
        return self.values[channel]

    def snapshot(self) -> dict[str, bool]:
        return dict(self.values)

@dataclass
class AnalogOutputs:
    names: list[str]
    values: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.values.setdefault(n, 0.0)

    def set_percent(self, channel: str, percent: float) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        self.values[channel] = max(0.0, min(100.0, float(percent)))

    def volts(self, channel: str) -> float:
        return self.values[channel] / 10.0

    def snapshot(self) -> dict[str, Any]:
        return {n: {'percent': p, 'volts': p / 10.0} for n, p in self.values.items()}


class I2CBus:
    def __init__(self, bus_id: int, enabled: bool = False):
        self.bus_id = bus_id
        self.enabled = enabled
        self.writes: list[tuple[int, int, int]] = []
        self._bus = None
        if enabled:
            try:
                from smbus2 import SMBus
            except ImportError as exc:
                raise RuntimeError("I2C enabled but smbus2 is not installed") from exc
            self._bus = SMBus(bus_id)

    def write_byte(self, address: int, value: int) -> None:
        self.writes.append((address, value, 0))
        if self._bus:
            self._bus.write_byte(address, value)

    def write_i2c_block_data(self, address: int, register: int, data: list[int]) -> None:
        self.writes.append((address, register, int.from_bytes(bytes(data), "big")))
        if self._bus:
            self._bus.write_i2c_block_data(address, register, data)


@dataclass(slots=True)
class I2CMux:
    bus: I2CBus
    address: int = 0x70
    selected_channel: int | None = None

    def select(self, channel: int) -> None:
        if channel < 0 or channel > 7:
            raise ValueError(f"invalid I2C mux channel: {channel}")
        self.bus.write_byte(self.address, 1 << channel)
        self.selected_channel = channel


@dataclass(slots=True)
class MCP4725:
    bus: I2CBus
    address: int = 0x60
    last_value: int = 0

    def set_raw(self, value: int) -> None:
        clipped = max(0, min(4095, int(value)))
        self.last_value = clipped
        self.bus.write_i2c_block_data(
            self.address,
            0x40,
            [(clipped >> 4) & 0xFF, (clipped & 0x0F) << 4],
        )


class MultiplexedDACOutputs(AnalogOutputs):
    def __init__(
        self,
        channels: dict[str, dict[str, Any]],
        bus: I2CBus,
        mux_address: int = 0x70,
        dac_address: int = 0x60,
    ):
        super().__init__(list(channels))
        self.channels = channels
        self.mux = I2CMux(bus, mux_address)
        self.dac = MCP4725(bus, dac_address)

    def set_percent(self, channel: str, percent: float) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        cfg = self.channels[channel]
        self.mux.select(int(cfg["mux_channel"]))
        super().set_percent(channel, percent)
        self.dac.set_raw(round(self.values[channel] / 100.0 * 4095))

    def snapshot(self) -> dict[str, Any]:
        base = super().snapshot()
        for channel, cfg in self.channels.items():
            base[channel] = {
                **base[channel],
                "mux_channel": cfg["mux_channel"],
                "dac_address": cfg["dac_address"],
            }
        return base
