from __future__ import annotations

import asyncio
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
            results[name] = {"commands": commands, "applied": apply and iface.enabled}
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
        return {
            "kind": kind,
            "address": address,
            "presence": bool(flags & 0x01),
            "temperature_c": payload[1] - 40,
            "humidity_pct": payload[2],
            "lux": lux,
            "aqi": payload[5],
            "status_flags": flags,
            "sensor_ok": {
                "bh1750": bool(flags & 0x02),
                "aht21": bool(flags & 0x04),
                "ens160": bool(flags & 0x08),
                "can": bool(flags & 0x10),
            },
            "any_sensor_fault": bool(flags & 0x20),
        }
    if kind == "heartbeat":
        uptime = (payload[4] << 24) | (payload[5] << 16) | (payload[6] << 8) | payload[7]
        return {
            "kind": kind,
            "address": address,
            "protocol_version": payload[0],
            "reported_address": payload[1],
            "fault_mask": payload[2],
            "status_flags": payload[3],
            "uptime_s": uptime,
        }
    return {
        "kind": kind,
        "address": address,
        "fault_mask": payload[0],
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


def configure_sync(config: dict[str, Any], apply: bool = False) -> dict[str, Any]:
    network = SocketCANNetwork.from_config(config)
    if not apply:
        return {
            name: {
                "commands": [
                    ["ip", "link", "set", name, "down"],
                    ["ip", "link", "set", name, "type", "can", "bitrate", str(iface.bitrate)],
                    ["ip", "link", "set", name, "up"],
                ],
                "applied": False,
            }
            for name, iface in network.interfaces.items()
        }
    for name, iface in network.interfaces.items():
        if not iface.enabled:
            continue
        subprocess.run(["ip", "link", "set", name, "down"], check=False)
        subprocess.run(["ip", "link", "set", name, "type", "can", "bitrate", str(iface.bitrate)], check=True)
        subprocess.run(["ip", "link", "set", name, "up"], check=True)
    return {name: {"applied": iface.enabled} for name, iface in network.interfaces.items()}
