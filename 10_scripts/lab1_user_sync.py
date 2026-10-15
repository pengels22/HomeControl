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
CONFIG_ROOT = Path("/opt/homecontrol-lab/state/homecontrol")


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


def apply_module_config_payload(payload: dict) -> dict:
    """Validate and persist an HCM configuration package for the active role."""
    package = payload.get("package") if isinstance(payload, dict) else None
    if not isinstance(package, dict):
        return {"ok": True, "applied": False}

    infra = importlib.import_module("module_infra")
    role = active_module_type()
    if role != "RCM":
        return {"ok": False, "error": "configuration role mismatch", "applied": False}
    infra.verify_config_package(package, module_type=role, logical_id="lab1")
    config = package.get("config")
    channels = config.get("channels") if isinstance(config, dict) else None
    if channels is None:
        return {"ok": True, "applied": False, "ignored": "module bootstrap configuration"}
    if not isinstance(channels, list) or len(channels) != 32:
        raise ValueError("RCM configuration must contain exactly 32 channels")

    store = infra.LocalConfigStore(CONFIG_ROOT, role, "lab1")
    current = store.load_json()
    current_config = current.get("config") if isinstance(current.get("config"), dict) else {}
    merged, conflicts = infra.reconcile_lockouts(config, current_config)
    merged_package = {**package, "config": merged}
    store.save_rcm_csv(merged["channels"])
    sync = {
        "state": "conflict" if conflicts else "synchronized",
        "last_synchronized_revision": package["revision"],
        "current_local_revision": package["revision"],
        "checksum": package["checksum"],
        "conflicts": conflicts,
    }
    store.save_json({**merged_package, "config_sync": sync})
    return {"ok": True, "applied": True, "config_sync": sync}
