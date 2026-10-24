"""Authoritative, non-actuating hardware profile loading and validation.

Hardware manifests describe the approved wiring model.  They do not enable
physical I/O.  A profile with unverified mappings is deliberately reported as
simulation-only so callers cannot turn documentation into an output path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_yaml


class HardwareProfileError(ValueError):
    """Raised when an authoritative hardware profile is incomplete or unsafe."""


@dataclass(frozen=True)
class HardwareProfile:
    module_type: str
    schema_version: int
    data: dict[str, Any]

    @property
    def physical_output_enabled(self) -> bool:
        return bool(self.data.get("physical_output_enabled", False))

    @property
    def verification_status(self) -> str:
        return str(self.data.get("verification", {}).get("status", "UNVERIFIED"))

    def capability_snapshot(self) -> dict[str, Any]:
        return {
            "module_type": self.module_type,
            "schema_version": self.schema_version,
            "processor": self.data.get("processor", {}),
            "faceplate": self.data.get("faceplate", {}),
            "verification": self.data.get("verification", {}),
            "physical_output_enabled": self.physical_output_enabled,
            "outputs": self.data.get("outputs", {}),
            "buses": self.data.get("buses", {}),
        }


def _require(mapping: dict[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise HardwareProfileError(f"{path} missing required key {key}")
    return mapping[key]


def validate_profile(data: dict[str, Any], expected_module: str | None = None) -> HardwareProfile:
    if not isinstance(data, dict):
        raise HardwareProfileError("hardware profile must be a mapping")
    module_type = str(_require(data, "module_type", "profile")).upper()
    if expected_module and module_type != expected_module.upper():
        raise HardwareProfileError(f"profile module_type {module_type} does not match {expected_module}")
    schema_version = int(_require(data, "schema_version", "profile"))
    header = _require(data, "processor_header", module_type)
    if not isinstance(header, dict):
        raise HardwareProfileError(f"{module_type}.processor_header must be a mapping")
    processor = _require(data, "processor", module_type)
    header_size = int(_require(processor, "header_pins", f"{module_type}.processor"))
    expected = {str(i) for i in range(1, header_size + 1)}
    actual = {str(k) for k in header}
    missing = sorted(expected - actual, key=int)
    extra = sorted(actual - expected, key=int)
    if missing or extra:
        raise HardwareProfileError(f"{module_type} header inventory mismatch; missing={missing}, extra={extra}")

    exclusive: dict[str, str] = {}
    for pin, entry in header.items():
        if not isinstance(entry, dict):
            raise HardwareProfileError(f"{module_type} header pin {pin} must be a mapping")
        _require(entry, "function", f"{module_type}.processor_header.{pin}")
        _require(entry, "verification", f"{module_type}.processor_header.{pin}")
        gpio = entry.get("gpio")
        if gpio and str(gpio).upper() not in {"UNVERIFIED", "TBD", "UNKNOWN"} and entry.get("exclusive", True):
            if gpio in exclusive:
                raise HardwareProfileError(
                    f"{module_type} duplicate exclusive GPIO {gpio}: pins {exclusive[gpio]} and {pin}"
                )
            exclusive[gpio] = str(pin)

    buses = data.get("buses", {})
    i2c_seen: dict[tuple[str, int], str] = {}
    for name, item in (buses.get("i2c", {}) or {}).items():
        if not isinstance(item, dict):
            raise HardwareProfileError(f"{module_type}.buses.i2c.{name} must be a mapping")
        if "address" not in item:
            continue
        if str(item["address"]).upper() in {"UNVERIFIED", "TBD", "UNKNOWN"}:
            continue
        bus = str(item.get("bus", "default"))
        address = int(str(item["address"]), 0)
        key = (bus, address)
        if key in i2c_seen:
            raise HardwareProfileError(
                f"{module_type} I2C address conflict on bus {bus}: {i2c_seen[key]} and {name} at 0x{address:02X}"
            )
        i2c_seen[key] = str(name)

    spi_seen: dict[tuple[str, str], str] = {}
    for name, item in (buses.get("spi", {}) or {}).items():
        if not isinstance(item, dict):
            raise HardwareProfileError(f"{module_type}.buses.spi.{name} must be a mapping")
        key = (str(item.get("controller", "default")), str(item.get("chip_select", "none")))
        if key in spi_seen:
            raise HardwareProfileError(f"{module_type} SPI conflict: {spi_seen[key]} and {name} use {key}")
        spi_seen[key] = str(name)

    verification = data.get("verification", {}) or {}
    if str(verification.get("status", "UNVERIFIED")).upper() not in {"DESIGN_APPROVED", "BENCH_TESTING", "SIMULATED", "BENCH_TESTED", "COMMISSIONED", "UNVERIFIED"}:
        raise HardwareProfileError(f"{module_type} has invalid verification status")
    if data.get("physical_output_enabled") and str(verification.get("status")).upper() != "COMMISSIONED":
        raise HardwareProfileError(f"{module_type} cannot enable physical outputs before commissioning")
    return HardwareProfile(module_type, schema_version, data)


def load_profile(path: str | Path, expected_module: str | None = None) -> HardwareProfile:
    return validate_profile(load_yaml(path), expected_module)


def profile_path(repo_root: str | Path, module_type: str) -> Path:
    directory = {"HCM": "02_HCM", "LCM": "03_LCM", "RCM": "04_RCM", "PNL": "05_PNL"}.get(module_type.upper())
    if not directory:
        raise HardwareProfileError(f"unsupported module type {module_type}")
    return Path(repo_root) / "07_config" / directory / "hardware_pins.yaml"
