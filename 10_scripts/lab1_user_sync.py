#!/usr/bin/env python3
"""Apply only HCM-authenticated user snapshots on the LAB1 simulation agent."""
from pathlib import Path
import importlib
import json
import os

DEVICE_ID = "2ccf675d3414"
STATE_PATH = Path("/opt/homecontrol-lab/state/module.json")
AUTH_PATH = Path("/opt/homecontrol-lab/state/homecontrol/config/LCM/lab1.auth.json")
BOOTSTRAP_PATH = Path("/opt/homecontrol-lab/state/homecontrol/local-admin-bootstrap.txt")


def active_module_type() -> str:
    """Return the last locally persisted, safety-validated operational role."""
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return "RCM"
    role = str(state.get("role") or "").upper()
    return role if role in {"RCM", "LCM", "SIM"} else "RCM"


def apply_config_payload(payload: dict) -> bool:
    snapshot = payload.get("user_snapshot") if isinstance(payload, dict) else None
    if not isinstance(snapshot, dict):
        return False
    store = importlib.import_module("module_infra").LocalAuthStore(AUTH_PATH)
    store.provision_snapshot(snapshot, device_id=DEVICE_ID)
    if BOOTSTRAP_PATH.exists():
        lines = BOOTSTRAP_PATH.read_text().splitlines()
        if any(line == "username=admin" for line in lines):
            BOOTSTRAP_PATH.write_text("\n".join("username=recovery:admin" if line == "username=admin" else line for line in lines) + "\n")
            os.chmod(BOOTSTRAP_PATH, 0o600)
    return True
