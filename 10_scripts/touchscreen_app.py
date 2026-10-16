"""Shared HomeControl touchscreen preview/runtime.

The default adapter is deliberately simulated and has no GPIO, SPI, I2C, CAN,
or network-control side effects. Real adapters can be injected after hardware
commissioning without changing the shared router or page model.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UI_ROOT = ROOT / "10_scripts" / "touchscreen_ui"
PROFILES = importlib.import_module("07_servises.common.hardware_profiles")


ROLE_PAGES = {
    "RCM": ["status", "relays", "network", "settings"],
    "LCM": ["status", "lights", "network", "settings"],
    "SIM": ["status", "rmc-data", "network", "settings"],
    "HCM": ["status", "sensors", "network", "settings"],
}


class Command(BaseModel):
    kind: str
    channel: str | None = None
    value: float | bool | None = None
    role: str = "RCM"
    authorized: bool = True


class SimulatedTouchscreenAdapter:
    """Read-only profile-backed state plus safe in-memory command acknowledgments."""

    def __init__(self, role: str):
        self.role = role.upper()
        if self.role not in ROLE_PAGES:
            raise ValueError(f"unsupported role {role}")
        self.profile = PROFILES.load_profile(PROFILES.profile_path(ROOT, self.role), self.role)
        self.state = self._initial_state()

    def _initial_state(self) -> dict[str, Any]:
        channels = {
            "RCM": [f"{bank}{i}" for bank in "ABCD" for i in range(1, 9)],
            "LCM": [f"A{i}" for i in range(1, 9)],
        }
        relay_names = channels.get(self.role, [])
        relays = [{"channel": ch, "name": ch, "on": False, "lockout": False, "confirmed": True} for ch in relay_names]
        dimmers = []
        if self.role == "LCM":
            dimmers = [
                {"channel": f"10-{i}", "name": f"10-{i}", "type": "0-10V", "percent": 0, "confirmed": True, "lockout": False}
                for i in range(1, 11)
            ] + [
                {"channel": f"HV-{i}", "name": f"HV-{i}", "type": "110V", "percent": 0, "confirmed": True, "lockout": False}
                for i in range(1, 5)
            ]
        rooms = []
        if self.role == "SIM":
            rooms = [{"name": "RMC-1", "online": False, "lux": None, "temperature_f": None, "humidity_pct": None, "presence": None}]
        external = []
        if self.role == "HCM":
            external = [
                {"name": "FIRE input", "value": "Unavailable", "source": "external safety input"},
                {"name": "AC monitor", "value": "Unavailable", "source": "external safety monitor"},
            ]
        return {
            "module": {"role": self.role, "name": f"{self.role}-01", "device_id": f"sim-{self.role.lower()}-preview", "simulation": True, "physical_outputs_enabled": False},
            "health": {"status": "SIMULATED", "heartbeat": "Unavailable", "config_sync": "Preview only", "faults": []},
            "network": {"hostname": f"{self.role.lower()}-preview", "ipv4": "Unavailable", "mac": "Unavailable", "link": "Simulated", "hcm": "Unavailable", "last_sync": "Unavailable"},
            "settings": {"display_brightness": 70, "inactivity_seconds": 10, "local_admin": "Enabled", "role": self.role, "simulation": "Enabled", "hardware_profile": self.profile.verification_status},
            "relays": relays,
            "dimmers": dimmers,
            "rooms": rooms,
            "external_sensors": external,
            "last_ack": None,
        }

    def snapshot(self) -> dict[str, Any]:
        data = copy.deepcopy(self.state)
        data["capabilities"] = ROLE_PAGES[self.role]
        data["hardware_profile"] = self.profile.capability_snapshot()
        return data

    def command(self, command: Command) -> dict[str, Any]:
        if not command.authorized:
            raise HTTPException(status_code=403, detail="authorized touchscreen session required")
        if command.role.upper() != self.role:
            raise HTTPException(status_code=409, detail="module role does not match touchscreen session")
        if command.kind not in {"relay", "dimmer"}:
            raise HTTPException(status_code=400, detail="unsupported simulated command")
        if not command.channel or command.value is None:
            raise HTTPException(status_code=422, detail="channel and value are required")
        if command.kind == "relay":
            item = next((x for x in self.state["relays"] if x["channel"] == command.channel), None)
            if not item:
                raise HTTPException(status_code=404, detail="relay unavailable")
            if item["lockout"]:
                raise HTTPException(status_code=409, detail="maintenance lockout prevents relay command")
            item["on"] = bool(command.value)
        else:
            item = next((x for x in self.state["dimmers"] if x["channel"] == command.channel), None)
            if not item:
                raise HTTPException(status_code=404, detail="dimmer unavailable")
            if item["lockout"]:
                raise HTTPException(status_code=409, detail="maintenance lockout prevents dimmer command")
            requested = max(0, min(100, round(float(command.value))))
            item["percent"] = 0 if requested <= 5 else requested
        ack = {"ok": True, "simulated": True, "physical_output_commanded": False, "channel": command.channel, "value": item.get("on", item.get("percent")), "acknowledged_at": time.time()}
        self.state["last_ack"] = ack
        return ack


adapters = {role: SimulatedTouchscreenAdapter(role) for role in ROLE_PAGES}
app = FastAPI(title="HomeControl Shared Touchscreen", version="preview")
app.mount("/assets", StaticFiles(directory=UI_ROOT), name="touchscreen-assets")


@app.get("/")
async def index():
    return FileResponse(UI_ROOT / "index.html")


@app.get("/api/touchscreen/state")
async def state(role: str = Query("RCM")):
    try:
        return adapters[role.upper()].snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unsupported module role") from exc


@app.post("/api/touchscreen/command")
async def command(payload: Command):
    try:
        return adapters[payload.role.upper()].command(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unsupported module role") from exc


def run(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
