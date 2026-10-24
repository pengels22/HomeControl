from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceInventoryEntry:
    name: str
    ssh_alias: str
    ip_address: str
    device_id: str
    device_type: str
    package: str
    hardware_platform: str
    architecture: str
    operating_system: str
    live_adapter: str
    simulation_only: bool = False
    notes: str = ""


INITIAL_INVENTORY: tuple[DeviceInventoryEntry, ...] = (
    DeviceInventoryEntry(
        name="jetson",
        ssh_alias="jetson",
        ip_address="192.168.20.27",
        device_id="48b02d87db16",
        device_type="HCM",
        package="01_HCM",
        hardware_platform="jetson_xavier_nx",
        architecture="aarch64",
        operating_system="ubuntu",
        live_adapter="hcm_docker",
        notes="Docker HCM with isolated PostgreSQL, Heartbeat V3, and watchdog.",
    ),
    DeviceInventoryEntry(
        name="conflict",
        ssh_alias="conflict",
        ip_address="192.168.20.26",
        device_id="3c53bbf7adb2",
        device_type="CONFLICT",
        package="07_CONFLICT",
        hardware_platform="raspberry_pi",
        architecture="aarch64",
        operating_system="debian",
        live_adapter="conflict_heartbeat",
        notes="Conflict Heartbeat V3 supervisor with SQLite registry.",
    ),
    DeviceInventoryEntry(
        name="lab1",
        ssh_alias="lab1",
        ip_address="192.168.20.36",
        device_id="2ccf675d3414",
        device_type="LAB",
        package="08_LAB",
        hardware_platform="raspberry_pi_4",
        architecture="aarch64",
        operating_system="debian",
        live_adapter="lab1_simulation",
        simulation_only=True,
        notes="Simulation-only LAB1; operational role is separate from deployment package.",
    ),
)


def normalize_device_id(value: str) -> str:
    normalized = value.replace(":", "").replace("-", "").strip().lower()
    if len(normalized) != 12 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise InventoryError(f"invalid device_id {value!r}")
    return normalized


def inventory() -> dict[str, DeviceInventoryEntry]:
    return {entry.name: entry for entry in INITIAL_INVENTORY}


def select_inventory(target: str | None = None) -> list[DeviceInventoryEntry]:
    entries = inventory()
    if target is None:
        return list(entries.values())
    if target not in entries:
        raise InventoryError(f"unknown target {target!r}")
    return [entries[target]]


def package_for_device(device_type: str, *, hardware_platform: str | None = None, device_id: str | None = None) -> str:
    device_type = device_type.upper()
    if device_id and normalize_device_id(device_id) == "2ccf675d3414":
        return "08_LAB"
    for entry in INITIAL_INVENTORY:
        if entry.device_type == device_type:
            return entry.package
    package_by_type = {
        "LCM": "03_LCM",
        "RCM": "04_RCM",
        "PNL": "05_PNL",
        "RMC": "06_RMC",
    }
    try:
        return package_by_type[device_type]
    except KeyError as exc:
        raise InventoryError(f"unsupported device_type {device_type!r}") from exc


def entry_to_dict(entry: DeviceInventoryEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "ssh_alias": entry.ssh_alias,
        "ip_address": entry.ip_address,
        "device_id": entry.device_id,
        "device_type": entry.device_type,
        "package": entry.package,
        "hardware_platform": entry.hardware_platform,
        "architecture": entry.architecture,
        "operating_system": entry.operating_system,
        "live_adapter": entry.live_adapter,
        "simulation_only": entry.simulation_only,
        "notes": entry.notes,
    }
