"""Production-shaped hardware drivers with interchangeable transports.

The drivers contain the register and transaction logic used by both physical
and LAB1 mock transports. Instantiating a driver does not authorize an output;
callers must enforce the commissioning gate before invoking output methods.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class HardwareTransportError(RuntimeError):
    pass


class I2CTransport(Protocol):
    def read_byte_data(self, address: int, register: int) -> int: ...
    def write_byte_data(self, address: int, register: int, value: int) -> None: ...
    def write_i2c_block_data(self, address: int, register: int, values: list[int]) -> None: ...
    def scan(self) -> list[int]: ...


@dataclass
class MockI2CTransport:
    registers: dict[tuple[int, int], int] = field(default_factory=dict)
    operations: list[dict[str, Any]] = field(default_factory=list)
    max_operations: int | None = 10_000
    operation_count: int = 0
    fail_reads: bool = False
    fail_writes: bool = False
    strict_registers: bool = False
    device_registers: dict[int, set[int]] = field(default_factory=dict)

    def _validate_register(self, address: int, register: int) -> None:
        if self.strict_registers and address in self.device_registers and register not in self.device_registers[address]:
            raise HardwareTransportError(f"mock register 0x{register:02X} is invalid for 0x{address:02X}")

    def _record(self, operation: dict[str, Any]) -> None:
        self.operation_count += 1
        if self.max_operations is not None and len(self.operations) >= self.max_operations:
            self.operations.pop(0)
        self.operations.append(operation)

    def read_byte_data(self, address: int, register: int) -> int:
        if self.fail_reads:
            raise HardwareTransportError("mock I2C read failure")
        self._validate_register(address, register)
        self._record({"op": "read", "address": address, "register": register})
        return self.registers.get((address, register), 0)

    def write_byte_data(self, address: int, register: int, value: int) -> None:
        if self.fail_writes:
            raise HardwareTransportError("mock I2C write failure")
        self._validate_register(address, register)
        value &= 0xFF
        self._record({"op": "write", "address": address, "register": register, "value": value})
        self.registers[(address, register)] = value

    def write_i2c_block_data(self, address: int, register: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            self.write_byte_data(address, register + offset, value)

    def scan(self) -> list[int]:
        return sorted({address for address, _ in self.registers})


class LinuxI2CTransport:
    """Explicit Linux transport; never selected implicitly by module config."""

    def __init__(self, bus_id: int):
        try:
            from smbus2 import SMBus
        except ImportError as exc:
            raise HardwareTransportError("smbus2 is required for Linux I2C") from exc
        self.bus_id = bus_id
        self.bus = SMBus(bus_id)

    def read_byte_data(self, address: int, register: int) -> int:
        return int(self.bus.read_byte_data(address, register))

    def write_byte_data(self, address: int, register: int, value: int) -> None:
        self.bus.write_byte_data(address, register, value & 0xFF)

    def write_i2c_block_data(self, address: int, register: int, values: list[int]) -> None:
        self.bus.write_i2c_block_data(address, register, [v & 0xFF for v in values])

    def scan(self) -> list[int]:
        found = []
        for address in range(0x03, 0x78):
            try:
                self.bus.read_byte(address)
            except OSError:
                continue
            found.append(address)
        return found

    def close(self) -> None:
        self.bus.close()


class LockedI2C:
    def __init__(self, transport: I2CTransport):
        self.transport = transport
        self.lock = threading.RLock()

    def read(self, address: int, register: int) -> int:
        with self.lock:
            return self.transport.read_byte_data(address, register)

    def write(self, address: int, register: int, value: int) -> None:
        with self.lock:
            self.transport.write_byte_data(address, register, value)

    def block(self, address: int, register: int, values: list[int]) -> None:
        with self.lock:
            self.transport.write_i2c_block_data(address, register, values)

    def scan(self) -> list[int]:
        with self.lock:
            return self.transport.scan()


class XL9535RelayDriver:
    """Two 16-bit XL9535 relay banks, active-low with safe-off startup."""

    OUTPUT = 0x02
    CONFIG = 0x06
    INPUT = 0x00

    def __init__(self, bus: LockedI2C, addresses: tuple[int, int] = (0x20, 0x21), active_low: bool = True):
        self.bus, self.addresses, self.active_low = bus, addresses, active_low
        self.shadow = {address: 0xFFFF for address in addresses}
        self.initialized = False

    def initialize(self) -> dict[str, Any]:
        for address in self.addresses:
            self.bus.block(address, self.OUTPUT, [0xFF, 0xFF])
            self.bus.block(address, self.CONFIG, [0x00, 0x00])
            self.shadow[address] = 0xFFFF
        self.initialized = True
        return {"ok": True, "addresses": [f"0x{x:02X}" for x in self.addresses], "safe_state": "all_off"}

    def _location(self, index: int) -> tuple[int, int]:
        if not 0 <= index < 32:
            raise ValueError("XL9535 relay index must be 0..31")
        return self.addresses[index // 16], index % 16

    def set_channel(self, index: int, on: bool, verify: bool = True) -> dict[str, Any]:
        if not self.initialized:
            raise HardwareTransportError("XL9535 driver is not initialized")
        address, bit = self._location(index)
        current = self.shadow[address]
        mask = 1 << bit
        output = (current & ~mask) if (on == self.active_low) else (current | mask)
        self.bus.block(address, self.OUTPUT, [output & 0xFF, (output >> 8) & 0xFF])
        self.shadow[address] = output
        readback = self.read_channel(index) if verify else bool(on)
        if verify and readback != bool(on):
            raise HardwareTransportError(f"XL9535 readback mismatch at relay {index}")
        return {"ok": True, "index": index, "on": bool(on), "readback": readback}

    def read_channel(self, index: int) -> bool:
        address, bit = self._location(index)
        low = self.bus.read(address, self.OUTPUT)
        high = self.bus.read(address, self.OUTPUT + 1)
        raw = low | (high << 8)
        self.shadow[address] = raw
        asserted = not bool(raw & (1 << bit)) if self.active_low else bool(raw & (1 << bit))
        return asserted

    def diagnostics(self) -> dict[str, Any]:
        return {"driver": "XL9535", "addresses": [f"0x{x:02X}" for x in self.addresses], "initialized": self.initialized, "shadow": dict(self.shadow)}


class MCP23017RelayDriver:
    """MCP23017 8-bit relay bank with active-low output preservation."""

    # BANK=0 is the reset/default register layout. The LCM relay contract is
    # Port B; Port A is reserved for selector/indicator infrastructure.
    IODIR = 0x01
    OLAT = 0x15

    def __init__(self, bus: LockedI2C, address: int, count: int = 8, active_low: bool = True):
        self.bus, self.address, self.count, self.active_low = bus, address, count, active_low
        self.shadow = 0xFF
        self.initialized = False

    def initialize(self) -> dict[str, Any]:
        self.bus.write(self.address, self.OLAT, 0xFF)
        self.bus.write(self.address, self.IODIR, 0x00)
        self.shadow, self.initialized = 0xFF, True
        return {"ok": True, "address": f"0x{self.address:02X}", "safe_state": "all_off"}

    def set_channel(self, index: int, on: bool, verify: bool = True) -> dict[str, Any]:
        if not self.initialized or not 0 <= index < self.count:
            raise HardwareTransportError("MCP23017 relay is not ready or index is invalid")
        mask = 1 << index
        value = (self.shadow & ~mask) if (on == self.active_low) else (self.shadow | mask)
        self.bus.write(self.address, self.OLAT, value)
        self.shadow = value
        readback = self.read_channel(index) if verify else bool(on)
        if verify and readback != bool(on):
            raise HardwareTransportError(f"MCP23017 readback mismatch at relay {index}")
        return {"ok": True, "index": index, "on": bool(on), "readback": readback}

    def read_channel(self, index: int) -> bool:
        value = self.bus.read(self.address, self.OLAT)
        self.shadow = value
        return not bool(value & (1 << index)) if self.active_low else bool(value & (1 << index))

    def diagnostics(self) -> dict[str, Any]:
        return {"driver": "MCP23017", "address": f"0x{self.address:02X}", "initialized": self.initialized, "shadow": self.shadow}


class MCP23017InputDriver:
    """MCP23017 input reader with pull-ups for RCM front-panel switches."""

    IODIRA = 0x00
    IODIRB = 0x01
    GPPUA = 0x0C
    GPPUB = 0x0D
    GPIOA = 0x12
    GPIOB = 0x13

    def __init__(self, bus: LockedI2C, mcp1_address: int = 0x26, mcp2_address: int = 0x27):
        self.bus = bus
        self.addresses = (int(mcp1_address), int(mcp2_address))
        self.initialized = False

    def initialize(self) -> dict[str, Any]:
        for address in self.addresses:
            self.bus.write(address, self.IODIRA, 0xFF)
            self.bus.write(address, self.IODIRB, 0xFF)
            self.bus.write(address, self.GPPUA, 0xFF)
            self.bus.write(address, self.GPPUB, 0xFF)
        self.initialized = True
        return {"ok": True, "addresses": [f"0x{x:02X}" for x in self.addresses], "mode": "inputs_pullup"}

    def read_ports(self) -> dict[str, int]:
        if not self.initialized:
            raise HardwareTransportError("MCP23017 input driver is not initialized")
        mcp1, mcp2 = self.addresses
        return {
            "mcp1_gpa": self.bus.read(mcp1, self.GPIOA),
            "mcp1_gpb": self.bus.read(mcp1, self.GPIOB),
            "mcp2_gpa": self.bus.read(mcp2, self.GPIOA),
        }

    def diagnostics(self) -> dict[str, Any]:
        return {"driver": "MCP23017_INPUT", "addresses": [f"0x{x:02X}" for x in self.addresses], "initialized": self.initialized}


class PCA9685Driver:
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0 = 0x06
    MODE1_RESTART = 0x80
    MODE1_AI = 0x20
    MODE1_SLEEP = 0x10
    FULL_OFF = 0x10

    def __init__(self, bus: LockedI2C, address: int = 0x40, frequency_hz: int = 1000):
        self.bus, self.address, self.frequency_hz = bus, address, frequency_hz
        self.values = [0] * 16
        self.initialized = False

    def initialize(self) -> dict[str, Any]:
        # PRE_SCALE is writable only while SLEEP is asserted. Auto-increment
        # is required for the four-byte LED channel transaction.
        self.bus.write(self.address, self.MODE1, self.MODE1_AI | self.MODE1_SLEEP)
        prescale = round(25_000_000 / (4096 * self.frequency_hz) - 1)
        self.bus.write(self.address, self.PRESCALE, max(3, min(255, prescale)))
        time.sleep(0.0005)
        self.bus.write(self.address, self.MODE1, self.MODE1_AI)
        time.sleep(0.0005)
        self.bus.write(self.address, self.MODE1, self.MODE1_AI | self.MODE1_RESTART)
        self.initialized = True
        return {"ok": True, "address": f"0x{self.address:02X}", "frequency_hz": self.frequency_hz}

    def set_percent(self, channel: int, percent: float, verify: bool = True) -> dict[str, Any]:
        if not self.initialized or not 0 <= channel < 16:
            raise HardwareTransportError("PCA9685 is not ready or channel is invalid")
        bounded = max(0.0, min(100.0, float(percent)))
        raw = round(bounded * 4095 / 100)
        register = self.LED0 + channel * 4
        # Normal PWM starts ON at count zero and ends at OFF=raw. At zero use
        # the device's full-OFF bit so the output is unambiguously disabled.
        off_high = ((raw >> 8) & 0x0F) | (self.FULL_OFF if raw == 0 else 0)
        self.bus.block(self.address, register, [0, 0, raw & 0xFF, off_high])
        self.values[channel] = raw
        return {"ok": True, "channel": channel, "percent": bounded, "raw": raw, "readback": raw if verify else None}

    def diagnostics(self) -> dict[str, Any]:
        return {"driver": "PCA9685", "address": f"0x{self.address:02X}", "initialized": self.initialized, "frequency_hz": self.frequency_hz, "values": list(self.values)}


class ShellyTransport(Protocol):
    def set_brightness(self, component: str, percent: float) -> dict[str, Any]: ...


@dataclass
class MockShellyTransport:
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def set_brightness(self, component: str, percent: float) -> dict[str, Any]:
        if not re.fullmatch(r"light:\d+", str(component)):
            raise HardwareTransportError("mock Shelly component must be light:<id>")
        if not math.isfinite(float(percent)):
            raise HardwareTransportError("mock Shelly brightness must be finite")
        call = {"component": component, "percent": max(0.0, min(100.0, float(percent)))}
        self.calls.append(call)
        return self.responses.get(component, {"ok": True, **call})


class ShellyRpcTransport:
    def __init__(self, base_url: str, request: Callable[..., Any] | None = None):
        self.base_url = base_url.rstrip("/")
        self.request = request or urllib.request.urlopen

    def set_brightness(self, component: str, percent: float) -> dict[str, Any]:
        body = json.dumps({"id": 1, "method": "Light.Set", "params": {"id": component, "brightness": round(percent)}}).encode()
        req = urllib.request.Request(self.base_url + "/rpc", data=body, headers={"Content-Type": "application/json"})
        with self.request(req, timeout=4) as response:
            result = json.loads(response.read().decode())
        if "error" in result:
            raise HardwareTransportError(str(result["error"]))
        return {"ok": True, "component": component, "percent": percent, "response": result}


@dataclass
class MockGPIOTransport:
    values: dict[int, bool | None] = field(default_factory=dict)
    operations: list[dict[str, Any]] = field(default_factory=list)

    def write(self, line: int, value: bool) -> None:
        self.values[line] = bool(value)
        self.operations.append({"line": line, "value": bool(value)})

    def read(self, line: int) -> bool | None:
        return self.values.get(line)


class LinuxGPIOInputTransport:
    """Read-only libgpiod input transport; never requests output lines."""

    def __init__(self, chip: str, line: int, consumer: str):
        try:
            import gpiod
            from gpiod.line import Direction
        except ImportError as exc:
            raise HardwareTransportError("gpiod is required for Linux GPIO inputs") from exc
        self.chip = chip
        self.line = int(line)
        self.request = gpiod.request_lines(
            chip,
            consumer=consumer,
            config={self.line: gpiod.LineSettings(direction=Direction.INPUT)},
        )

    def read(self, line: int | None = None) -> bool:
        requested_line = self.line if line is None else int(line)
        value = self.request.get_value(requested_line)
        return bool(getattr(value, "value", value))

    def close(self) -> None:
        self.request.release()


class DebouncedInput:
    def __init__(self, debounce_ms: int = 50):
        self.debounce_s = debounce_ms / 1000
        self.last_value: Any = None
        self.last_change = 0.0

    def update(self, value: Any, now: float | None = None) -> Any | None:
        now = time.monotonic() if now is None else now
        if value != self.last_value:
            self.last_value, self.last_change = value, now
            return None
        if now - self.last_change >= self.debounce_s:
            return value
        return None


def build_lab1_mock_drivers(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Instantiate production driver classes with recording, non-physical transports."""
    transport = MockI2CTransport()
    bus = LockedI2C(transport)
    profile = profile or {}
    i2c = profile.get('buses', {}).get('i2c', {})
    mcp_address = int(str(i2c.get('mcp2', {}).get('address', 0x27)), 0)
    pwm_address = int(str(i2c.get('pca9685', {}).get('address', 0x40)), 0)
    return {
        "i2c_transport": transport,
        "rcm_relays": XL9535RelayDriver(bus),
        "rcm_inputs": MCP23017InputDriver(bus, 0x26, 0x27),
        "lcm_relays": MCP23017RelayDriver(bus, mcp_address),
        "lcm_pwm": PCA9685Driver(bus, pwm_address, int(i2c.get('pca9685', {}).get('frequency_hz', 1000))),
        "shelly_1": MockShellyTransport(),
        "shelly_2": MockShellyTransport(),
        "gpio": MockGPIOTransport(),
        "bank_selector": DebouncedInput(),
    }
