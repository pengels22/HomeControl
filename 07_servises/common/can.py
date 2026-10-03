from __future__ import annotations

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


RMC_FRAME_KIND = {
    0x100: "telemetry",
    0x200: "heartbeat",
    0x300: "fault",
    0x400: "fault_clear",
}

RMC_SENSOR_DEFINITIONS = {
    "aht21": {
        "label": "AHT21 temperature/humidity",
        "interface": "i2c",
        "address": "0x38",
        "telemetry": ["temperature_c", "humidity_pct"],
        "health_bit": 2,
    },
    "ens160": {
        "label": "ENS160 air quality",
        "interface": "i2c",
        "address": "0x52",
        "telemetry": ["aqi"],
        "health_bit": 3,
    },
    "bh1750": {
        "label": "BH1750 ambient light",
        "interface": "i2c",
        "address": "0x23",
        "telemetry": ["lux"],
        "health_bit": 1,
    },
    "rcwl_0516": {
        "label": "RCWL-0516 presence",
        "interface": "gpio",
        "pin": "D3",
        "telemetry": ["presence"],
        "health_bit": None,
    },
    "mcp2515_tja1050": {
        "label": "MCP2515 + TJA1050 CAN interface",
        "interface": "spi",
        "cs_pin": "D10",
        "int_pin": "D2",
        "telemetry": ["can"],
        "health_bit": 4,
    },
}

RMC_FAULT_BITS = {
    0x01: "bh1750",
    0x02: "aht21",
    0x04: "ens160",
    0x08: "can",
}


@dataclass(slots=True)
class CANInterface:
    name: str
    label: str
    bitrate: int = 125000
    enabled: bool = False
    last_configured_at: float | None = None
    rx_count: int = 0
    tx_count: int = 0
    last_frame: dict[str, Any] | None = None


@dataclass
class SocketCANNetwork:
    interfaces: dict[str, CANInterface] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SocketCANNetwork":
        items = config.get("can_interfaces", [])
        interfaces = {
            item["name"]: CANInterface(
                name=item["name"],
                label=item.get("label", item["name"]),
                bitrate=int(item.get("bitrate", config.get("can_bitrate", 125000))),
                enabled=bool(item.get("enabled", config.get("can_enabled", False))),
            )
            for item in items
        }
        return cls(interfaces)

    def snapshot(self) -> dict[str, Any]:
        return {
            name: {
                "label": iface.label,
                "bitrate": iface.bitrate,
                "enabled": iface.enabled,
                "last_configured_at": iface.last_configured_at,
                "rx_count": iface.rx_count,
                "tx_count": iface.tx_count,
                "last_frame": iface.last_frame,
            }
            for name, iface in self.interfaces.items()
        }

    def setup_plan(self) -> dict[str, Any]:
        return socketcan_setup_plan({
            "can_interfaces": [
                {
                    "name": iface.name,
                    "label": iface.label,
                    "bitrate": iface.bitrate,
                    "enabled": iface.enabled,
                }
                for iface in self.interfaces.values()
            ]
        })

    def record_frame(self, interface: str, arbitration_id: int, data: list[int]) -> None:
        iface = self.interfaces[interface]
        iface.rx_count += 1
        iface.last_frame = {
            "arbitration_id": arbitration_id,
            "data": data,
            "ts": time.time(),
        }

    async def configure(self, apply: bool = False) -> dict[str, Any]:
        results: dict[str, Any] = {}
        modules = ["can", "can_raw", "gs_usb"]
        if apply:
            for module in modules:
                proc = await asyncio.create_subprocess_exec(
                    "modprobe",
                    module,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(f"modprobe {module} failed: {out.decode(errors='replace')}")
        for name, iface in self.interfaces.items():
            commands = [
                ["ip", "link", "set", name, "down"],
                ["ip", "link", "set", name, "type", "can", "bitrate", str(iface.bitrate)],
                ["ip", "link", "set", name, "up"],
            ]
            if apply and iface.enabled:
                for command in commands:
                    proc = await asyncio.create_subprocess_exec(
                        *command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    out, _ = await proc.communicate()
                    if proc.returncode != 0:
                        raise RuntimeError(f"{' '.join(command)} failed: {out.decode(errors='replace')}")
                iface.last_configured_at = time.time()
            results[name] = {
                "modules": modules,
                "commands": commands,
                "applied": apply and iface.enabled,
            }
        return results


def rmc_frame_address(arbitration_id: int) -> int:
    return (arbitration_id >> 4) & 0x0F


def rmc_frame_kind(arbitration_id: int) -> str | None:
    return RMC_FRAME_KIND.get(arbitration_id & 0xF00)


def decode_rmc_frame(arbitration_id: int, data: list[int]) -> dict[str, Any] | None:
    kind = rmc_frame_kind(arbitration_id)
    if not kind:
        return None
    payload = [int(v) & 0xFF for v in data]
    payload = (payload + [0] * 8)[:8]
    address = rmc_frame_address(arbitration_id)
    if kind == "telemetry":
        flags = payload[0]
        lux = (payload[3] << 8) | payload[4]
        sensor_ok = {
            "bh1750": bool(flags & 0x02),
            "aht21": bool(flags & 0x04),
            "ens160": bool(flags & 0x08),
            "can": bool(flags & 0x10),
            "rcwl_0516": True,
        }
        return {
            "kind": kind,
            "address": address,
            "presence": bool(flags & 0x01),
            "temperature_c": payload[1] - 40,
            "humidity_pct": payload[2],
            "lux": lux,
            "aqi": payload[5],
            "status_flags": flags,
            "sensor_ok": sensor_ok,
            "sensor_faults": [name for name, ok in sensor_ok.items() if not ok],
            "any_sensor_fault": bool(flags & 0x20),
        }
    if kind == "heartbeat":
        uptime = (payload[4] << 24) | (payload[5] << 16) | (payload[6] << 8) | payload[7]
        fault_mask = payload[2]
        return {
            "kind": kind,
            "address": address,
            "protocol_version": payload[0],
            "reported_address": payload[1],
            "fault_mask": fault_mask,
            "faults": [name for bit, name in RMC_FAULT_BITS.items() if fault_mask & bit],
            "status_flags": payload[3],
            "uptime_s": uptime,
        }
    fault_mask = payload[0]
    return {
        "kind": kind,
        "address": address,
        "fault_mask": fault_mask,
        "faults": [name for bit, name in RMC_FAULT_BITS.items() if fault_mask & bit],
        "status_flags": payload[1],
        "reported_address": payload[2],
        "protocol_version": payload[3],
    }


def encode_rmc_telemetry(
    address: int,
    *,
    presence: bool,
    temperature_c: int,
    humidity_pct: int,
    lux: int,
    aqi: int,
    healthy: bool = True,
) -> tuple[int, list[int]]:
    flags = 0x10
    if presence:
        flags |= 0x01
    if healthy:
        flags |= 0x02 | 0x04 | 0x08
    else:
        flags |= 0x20
    clipped_lux = max(0, min(65535, int(lux)))
    data = [
        flags,
        max(0, min(255, int(round(temperature_c)) + 40)),
        max(0, min(100, int(round(humidity_pct)))),
        (clipped_lux >> 8) & 0xFF,
        clipped_lux & 0xFF,
        max(0, min(5, int(aqi))),
        0,
        0,
    ]
    return 0x100 | ((address & 0x0F) << 4), data


def socketcan_setup_plan(config: dict[str, Any]) -> dict[str, Any]:
    network = SocketCANNetwork.from_config(config)
    modules = config.get("can_kernel_modules", ["can", "can_raw", "gs_usb"])
    return {
        name: {
            "modules": modules,
            "hardware": next((item.get("hardware") for item in config.get("can_interfaces", []) if item.get("name") == name), None),
            "connector": next((item.get("connector") for item in config.get("can_interfaces", []) if item.get("name") == name), None),
            "driver": next((item.get("driver") for item in config.get("can_interfaces", []) if item.get("name") == name), "gs_usb"),
            "commands": [
                ["ip", "link", "set", name, "down"],
                ["ip", "link", "set", name, "type", "can", "bitrate", str(iface.bitrate)],
                ["ip", "link", "set", name, "up"],
            ],
            "applied": False,
        }
        for name, iface in network.interfaces.items()
    }


def socketcan_status(config: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {}
    for item in config.get("can_interfaces", []):
        name = item["name"]
        sys_path = f"/sys/class/net/{name}"
        exists = os.path.exists(sys_path)
        driver = None
        if exists:
            driver_link = os.path.join(sys_path, "device", "driver")
            if os.path.exists(driver_link):
                driver = os.path.basename(os.path.realpath(driver_link))
        status[name] = {
            "exists": exists,
            "enabled": bool(item.get("enabled", config.get("can_enabled", False))),
            "expected_driver": item.get("driver", "gs_usb"),
            "driver": driver,
            "hardware": item.get("hardware"),
            "connector": item.get("connector"),
        }
    return status


def configure_sync(config: dict[str, Any], apply: bool = False) -> dict[str, Any]:
    network = SocketCANNetwork.from_config(config)
    modules = config.get("can_kernel_modules", ["can", "can_raw", "gs_usb"])
    if not apply:
        return socketcan_setup_plan(config)
    for module in modules:
        subprocess.run(["modprobe", module], check=True)
    for name, iface in network.interfaces.items():
        if not iface.enabled:
            continue
        subprocess.run(["ip", "link", "set", name, "down"], check=False)
        subprocess.run(["ip", "link", "set", name, "type", "can", "bitrate", str(iface.bitrate)], check=True)
        subprocess.run(["ip", "link", "set", name, "up"], check=True)
    return {
        name: {
            "modules": modules,
            "applied": iface.enabled,
            "status": socketcan_status(config).get(name),
        }
        for name, iface in network.interfaces.items()
    }
