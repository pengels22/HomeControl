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


def pending_config_path(role: str = "RCM") -> Path:
    return CONFIG_ROOT / "config" / role.upper() / "lab1.pending.json"


def queue_local_config_update(role: str, channels: list[dict], actor: str) -> dict:
    """Persist a local edit and durable outbound package before it is sent."""
    infra = importlib.import_module("module_infra")
    role = role.upper()
    store = infra.LocalConfigStore(CONFIG_ROOT, role, "lab1")
    current = store.load_json()
    current_sync = current.get("config_sync") if isinstance(current.get("config_sync"), dict) else {}
    base_revision = current_sync.get("last_synchronized_revision")
    config = {"channels": channels}
    package = infra.build_config_package(role, "lab1", config)
    sync = {
        "state": "local_changes_pending_hcm_reconciliation",
        "origin": "local_emergency_config",
        "actor": actor,
        "base_revision": base_revision,
        "local_revision": package["revision"],
        "checksum": package["checksum"],
        "attempts": 0,
    }
    store.save_json({**package, "config_sync": sync, "local_edit_by": actor})
    path = pending_config_path(role)
    infra.atomic_write_text(path, json.dumps({"package": package, "base_revision": base_revision, "config_sync": sync}, indent=2, sort_keys=True))
    return {"revision": package["revision"], "checksum": package["checksum"], "base_revision": base_revision, "state": sync["state"]}


def pending_config_update(role: str = "RCM") -> dict | None:
    path = pending_config_path(role)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("package"), dict) else None


def claim_pending_config(role: str = "RCM") -> tuple[dict, str] | None:
    pending = pending_config_update(role)
    if not pending or pending.get("request_id"):
        return None
    request_id = __import__("uuid").uuid4().hex
    pending["request_id"] = request_id
    pending["attempts"] = int(pending.get("attempts", 0)) + 1
    infra = importlib.import_module("module_infra")
    infra.atomic_write_text(pending_config_path(role), json.dumps(pending, indent=2, sort_keys=True))
    return pending, request_id


def mark_config_update_ack(role: str, ack: dict) -> None:
    path = pending_config_path(role)
    pending = pending_config_update(role)
    if not pending:
        return
    infra = importlib.import_module("module_infra")
    store = infra.LocalConfigStore(CONFIG_ROOT, role, "lab1")
    current = store.load_json()
    sync = current.get("config_sync") if isinstance(current.get("config_sync"), dict) else {}
    if ack.get("ok"):
        sync = {**sync, "state": "synchronized", "last_synchronized_revision": ack.get("revision") or pending["package"]["revision"], "checksum": ack.get("checksum") or pending["package"]["checksum"], "origin": "local_emergency_config"}
        store.save_json({**current, "config_sync": sync})
        path.unlink(missing_ok=True)
    else:
        sync = {**sync, "state": "local_changes_pending_hcm_reconciliation", "last_error": ack.get("error", "HCM rejected configuration")}
        store.save_json({**current, "config_sync": sync})


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
    if pending_config_update(role):
        return {"ok": True, "applied": False, "deferred": "local configuration pending HCM reconciliation"}
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
