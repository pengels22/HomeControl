"""Explicit construction of module hardware transports and drivers.

Construction is deliberately separate from authorization.  A real bundle may
be created only when the module explicitly selects ``real`` I/O, and a failed
transport construction raises instead of silently changing the mode to mock or
simulated.  Output writes still require the manifest commissioning gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import physical_drivers as drivers


@dataclass
class HardwareDriverBundle:
    mode: str
    transport_type: str
    rcm_relays: Any | None = None
    lcm_relays: Any | None = None
    lcm_pwm: Any | None = None
    shelly_1: Any | None = None
    shelly_2: Any | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    transports: list[Any] = field(default_factory=list)

    def close(self) -> None:
        """Close owned transports; safe to call repeatedly."""
        for transport in self.transports:
            close = getattr(transport, "close", None)
            if close is not None:
                close()
        self.transports.clear()

    def as_dict(self) -> dict[str, Any]:
        result = {
            "mode": self.mode,
            "transport_type": self.transport_type,
            "diagnostics": dict(self.diagnostics),
        }
        for name in ("rcm_relays", "lcm_relays", "lcm_pwm", "shelly_1", "shelly_2"):
            driver = getattr(self, name)
            if driver is not None and hasattr(driver, "diagnostics"):
                result[name] = driver.diagnostics()
        return result

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def items(self):
        return ((name, getattr(self, name)) for name in ("rcm_relays", "lcm_relays", "lcm_pwm", "shelly_1", "shelly_2"))


def _profile_data(profile: dict[str, Any] | None) -> dict[str, Any]:
    return profile if isinstance(profile, dict) else {}


def _address(profile: dict[str, Any], name: str, default: int) -> int:
    item = profile.get("buses", {}).get("i2c", {}).get(name, {})
    raw = item.get("address", default) if isinstance(item, dict) else default
    return int(str(raw), 0)


def _bus_id(config: dict[str, Any], profile: dict[str, Any]) -> int:
    i2c = config.get("i2c", {})
    if isinstance(i2c, dict) and "bus" in i2c:
        return int(i2c["bus"])
    device = i2c.get("device") if isinstance(i2c, dict) else None
    if device and str(device).startswith("/dev/i2c-"):
        return int(str(device).rsplit("-", 1)[1])
    for item in profile.get("buses", {}).get("i2c", {}).values():
        if isinstance(item, dict) and str(item.get("device", "")).startswith("/dev/i2c-"):
            return int(str(item["device"]).rsplit("-", 1)[1])
    raise ValueError("real I2C mode requires explicit Linux bus mapping")


def build_hardware_bundle(
    module_type: str,
    config: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> HardwareDriverBundle:
    """Build the requested bundle without changing its requested mode."""
    mode = str(config.get("hardware_mode", config.get("io_mode", "simulated"))).lower()
    if mode == "auto":
        mode = "simulated"
    if mode not in {"simulated", "mock", "real", "disabled"}:
        raise ValueError("hardware mode must be simulated, mock, real, or disabled")
    profile = _profile_data(profile or config.get("hardware_profile"))
    module_type = module_type.upper()
    if mode in {"simulated", "disabled"}:
        return HardwareDriverBundle(mode=mode, transport_type="none", diagnostics={"status": "not_instantiated"})

    if mode == "mock":
        bundle = drivers.build_lab1_mock_drivers(profile=profile)
        return HardwareDriverBundle(
            mode="mock",
            transport_type="mock",
            rcm_relays=bundle.get("rcm_relays"),
            lcm_relays=bundle.get("lcm_relays"),
            lcm_pwm=bundle.get("lcm_pwm"),
            shelly_1=bundle.get("shelly_1"),
            shelly_2=bundle.get("shelly_2"),
            diagnostics={"status": "mock_only", "transport": bundle.get("i2c_transport")},
        )

    # Real mode intentionally has no fallback.  Missing smbus2, bus access,
    # or a malformed manifest is a startup error.
    if module_type not in {"RCM", "LCM"}:
        return HardwareDriverBundle(mode="real", transport_type="none", diagnostics={"status": "not_configured"})
    i2c_transport = drivers.LinuxI2CTransport(_bus_id(config, profile))
    bus = drivers.LockedI2C(i2c_transport)
    bundle = HardwareDriverBundle(mode="real", transport_type="linux_i2c", transports=[i2c_transport])
    if module_type == "RCM":
        addresses = tuple(
            _address(profile, name, default)
            for name, default in (("relay_card_1", 0x20), ("relay_card_2", 0x21))
        )
        bundle.rcm_relays = drivers.XL9535RelayDriver(bus, addresses=addresses)
    else:
        bundle.lcm_relays = drivers.MCP23017RelayDriver(bus, _address(profile, "mcp2", 0x27))
        pwm = profile.get("buses", {}).get("i2c", {}).get("pca9685", {})
        bundle.lcm_pwm = drivers.PCA9685Driver(
            bus,
            _address(profile, "pca9685", 0x40),
            int((pwm or {}).get("frequency_hz", 1000)),
        )
        hv = profile.get("outputs", {}).get("hv_dimmers", {}).get("mappings", {})
        for key, slot in (("shelly_1", "shelly_1"), ("shelly_2", "shelly_2")):
            endpoint = next((item.get("device") or item.get("url") for item in hv.values() if item.get("device_slot") == key), None)
            if endpoint:
                setattr(bundle, slot, drivers.ShellyRpcTransport(str(endpoint)))
            else:
                bundle.diagnostics[f"{slot}_status"] = "not_configured"
    bundle.diagnostics.update({"status": "constructed", "physical_writes": "commissioning_required", "initialization_owner": "module_agent"})
    return bundle
