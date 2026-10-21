"""Shared HomeControl touchscreen preview/runtime.

The default adapter is deliberately simulated and has no GPIO, SPI, I2C, CAN,
or network-control side effects. Real adapters can be injected after hardware
commissioning without changing the shared router or page model.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
common_contract = importlib.import_module("08_servises.common.control_contract")


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UI_ROOT = ROOT / "11_scripts" / "touchscreen_ui"
PROFILES = importlib.import_module("08_servises.common.hardware_profiles")


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
    bank: int | None = None
    setting: str | None = None
    role: str = "RCM"
    # Deprecated compatibility input. It can only reject a request; it never
    # grants authority. Production authority comes from the server session.
    authorized: bool | None = None
    logical_name: str | None = None


class HcmAuthoritativeTouchscreenAdapter:
    """Forward commands to HCM's logical command API; never fall back locally."""

    def __init__(self, role: str):
        self.role = role
        self.base_url = os.environ["HOMECONTROL_HCM_API_URL"].rstrip("/")
        self.token = os.environ.get("HOMECONTROL_HCM_TOKEN", "")
        if not self.token:
            raise RuntimeError("production touchscreen mode requires HOMECONTROL_HCM_TOKEN")
        try:
            self.logical_map = json.loads(os.environ.get("HOMECONTROL_TOUCHSCREEN_LOGICAL_MAP", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("HOMECONTROL_TOUCHSCREEN_LOGICAL_MAP must be JSON") from exc
        if not isinstance(self.logical_map, dict) or not self.logical_map:
            raise RuntimeError("production touchscreen mode requires logical bindings")

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise HTTPException(exc.code, detail or "HCM command failed") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise HTTPException(503, "HCM authoritative control unavailable") from exc

    def snapshot(self) -> dict[str, Any]:
        return self._request(f"/touchscreen/state?role={self.role}")

    def command(self, command: Command) -> dict[str, Any]:
        logical_name = command.logical_name or self.logical_map.get(f"{self.role}:{command.channel}")
        if not logical_name:
            raise HTTPException(409, "logical touchscreen binding is unavailable")
        module_command = common_contract.normalize_touch_command(command.model_dump())
        result = self._request("/device/command", {"logical_name": logical_name, "command": module_command})
        return common_contract.command_ack(result=result, logical_name=logical_name, channel=str(command.channel))


class SimulatedTouchscreenAdapter:
    """Read-only profile-backed state plus safe in-memory command acknowledgments."""

    def __init__(self, role: str):
        self.role = role.upper()
        if self.role not in ROLE_PAGES:
            raise ValueError(f"unsupported role {role}")
        self.profile = PROFILES.load_profile(PROFILES.profile_path(ROOT, self.role), self.role)
        self.settings_path = Path(os.getenv("HOMECONTROL_TOUCHSCREEN_STATE_DIR", str(ROOT / "tmp" / "touchscreen-state"))) / f"{self.role.lower()}-settings.json"
        self.state = self._initial_state()

    def _saved_timeout(self) -> int:
        try:
            value = json.loads(self.settings_path.read_text()).get("inactivity_seconds", 10)
            return max(1, min(300, int(value)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 10

    def _save_timeout(self, value: int) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"inactivity_seconds": value}) + "\n")

    def _initial_state(self) -> dict[str, Any]:
        channels = {
            "RCM": [f"{bank}{i}" for bank in "ABCD" for i in range(1, 9)],
            "LCM": [f"A{i}" for i in range(1, 9)],
        }
        relay_names = channels.get(self.role, [])
        relays = [{"channel": ch, "position": index, "name": (f"Relay {index}" if self.role == "RCM" else ch), "on": False, "lockout": False, "confirmed": True} for index, ch in enumerate(relay_names, start=1)]
        dimmers = []
        if self.role == "LCM":
            dimmers = [
                {"channel": f"10-{i}", "name": f"10-{i}", "type": "0-10V", "percent": 0, "confirmed": True, "lockout": False}
                for i in range(1, 11)
            ] + [
                {"channel": f"HV-{i}", "name": f"HV-{i}", "type": "110V", "driver": "shelly", "percent": 0, "confirmed": True, "lockout": False}
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
            "settings": {"display_brightness": 70, "inactivity_seconds": self._saved_timeout(), "local_admin": "Enabled", "role": self.role, "simulation": "Enabled", "hardware_profile": self.profile.verification_status},
            "relays": relays,
            "dimmers": dimmers,
            "rooms": rooms,
            "external_sensors": external,
            "last_ack": None,
            "bank_selector": {"touchscreen_bank": 0, "physical_bank": None, "physical_selector_authoritative": False, "effective_bank": 0, "source": "touchscreen"},
            "state_revision": 0,
        }

    def snapshot(self) -> dict[str, Any]:
        data = copy.deepcopy(self.state)
        data["capabilities"] = ROLE_PAGES[self.role]
        data["hardware_profile"] = self.profile.capability_snapshot()
        return data

    def command(self, command: Command) -> dict[str, Any]:
        if command.authorized is False:
            raise HTTPException(status_code=403, detail="client authorization fields cannot grant authority")
        if command.role.upper() != self.role:
            raise HTTPException(status_code=409, detail="module role does not match touchscreen session")
        if command.kind == "setting":
            if command.setting != "screen_timeout":
                raise HTTPException(status_code=403, detail="only screen timeout is editable")
            try:
                timeout = int(command.value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="screen timeout must be an integer") from exc
            if not 1 <= timeout <= 300:
                raise HTTPException(status_code=422, detail="screen timeout must be between 1 and 300 seconds")
            self.state["settings"]["inactivity_seconds"] = timeout
            self._save_timeout(timeout)
            self.state["state_revision"] += 1
            ack = {"ok": True, "simulated": True, "setting": command.setting, "value": timeout, "state_revision": self.state["state_revision"]}
            self.state["last_ack"] = ack
            return ack
        if command.kind == "bank_select":
            if self.role != "RCM" or command.bank not in range(4):
                raise HTTPException(status_code=400, detail="invalid RCM bank selection")
            selector = self.state["bank_selector"]
            selector["touchscreen_bank"] = command.bank
            if selector["physical_selector_authoritative"] and selector["physical_bank"] is not None:
                selector["effective_bank"] = selector["physical_bank"]
                selector["source"] = "physical"
            else:
                selector["effective_bank"] = command.bank
                selector["source"] = "touchscreen"
            self.state["state_revision"] += 1
            return {"ok": True, "simulated": True, "physical_output_commanded": False, "bank": selector["effective_bank"], "source": selector["source"]}
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
            item["percent"] = 0 if requested < 5 else requested
        self.state["state_revision"] += 1
        ack = {"ok": True, "simulated": True, "physical_output_commanded": False, "channel": command.channel, "value": item.get("on", item.get("percent")), "acknowledged_at": time.time()}
        self.state["last_ack"] = ack
        return ack

    def update_physical_bank(self, bank: int) -> None:
        """Apply a hardware selector update; physical input wins over touch requests."""
        if self.role != "RCM" or bank not in range(4):
            raise ValueError("invalid RCM bank")
        self.state["bank_selector"].update({"physical_bank": bank, "physical_selector_authoritative": True, "effective_bank": bank, "source": "physical"})


TOUCHSCREEN_MODE = os.getenv("HOMECONTROL_TOUCHSCREEN_MODE", "simulation").lower()
if TOUCHSCREEN_MODE == "production":
    adapters = {role: HcmAuthoritativeTouchscreenAdapter(role) for role in ROLE_PAGES}
elif TOUCHSCREEN_MODE == "simulation":
    adapters = {role: SimulatedTouchscreenAdapter(role) for role in ROLE_PAGES}
else:
    raise RuntimeError("HOMECONTROL_TOUCHSCREEN_MODE must be simulation or production")
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
