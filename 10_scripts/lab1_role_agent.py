#!/usr/bin/env python3
"""LAB1 simulation role helper for manual deployment.

This file is intentionally repository-delivered only. Codex must not install it
on LAB1 automatically. The helper contains no private keys and performs no
network, hostname, GPIO, relay, dimmer, CAN, I2C, SPI or VLAN changes.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any


LAB1_DEVICE_ID = "2ccf675d3414"
ALLOWED_ROLES = {"UNASSIGNED", "RCM", "SIM", "LCM"}
OPERATION_HISTORY_KEY = "role_operation_history"


class RoleCommandError(ValueError):
    pass


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "device_id": LAB1_DEVICE_ID,
            "hostname": "lab1",
            "role": "UNASSIGNED",
            "simulation": True,
            "physical_outputs_enabled": False,
            "commissioned": False,
            OPERATION_HISTORY_KEY: {},
        }
    return json.loads(path.read_text())


def save_state_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    uid = os.getuid()
    gid = os.getgid()
    mode = 0o644
    try:
        current = path.stat()
        uid = current.st_uid
        gid = current.st_gid
        mode = current.st_mode & 0o777
    except FileNotFoundError:
        pass
    mode = 0o644 if mode == 0 else mode
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as tmp:
            try:
                os.fchown(tmp.fileno(), uid, gid)
            except PermissionError:
                pass
            os.fchmod(tmp.fileno(), mode)
            json.dump(state, tmp, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        try:
            os.chown(path, uid, gid)
        except PermissionError:
            pass
        os.chmod(path, mode)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _canonical_uuid(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoleCommandError(f"missing {field_name}")
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise RoleCommandError(f"invalid {field_name}") from None
    return str(parsed)


def _operation_record(payload: dict[str, Any], operation_id: str) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "device_id": payload.get("device_id"),
        "requested_role": str(payload.get("requested_role") or "").upper(),
        "simulation_required": payload.get("simulation_required") is True,
    }


def _history(state: dict[str, Any]) -> dict[str, Any]:
    existing = state.get(OPERATION_HISTORY_KEY)
    if isinstance(existing, dict):
        return existing
    migrated: dict[str, Any] = {}
    for operation_id in state.get("applied_operations") or []:
        if isinstance(operation_id, str):
            migrated[operation_id] = {
                "operation_id": operation_id,
                "device_id": state.get("device_id", LAB1_DEVICE_ID),
                "requested_role": state.get("role", "UNASSIGNED"),
                "simulation_required": True,
            }
    state[OPERATION_HISTORY_KEY] = migrated
    state.pop("applied_operations", None)
    return migrated


def _validate_safe_state(state: dict[str, Any]) -> None:
    if state.get("device_id") != LAB1_DEVICE_ID:
        raise RoleCommandError("state device_id does not match LAB1")
    if state.get("hostname") not in (None, "lab1"):
        raise RoleCommandError("state hostname does not match LAB1")
    if state.get("simulation") is not True:
        raise RoleCommandError("LAB1 state must remain simulation-only")
    if state.get("physical_outputs_enabled") is not False:
        raise RoleCommandError("LAB1 physical outputs must remain inhibited")


def apply_role_command(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any]:
    if payload.get("op") != "set_module_role":
        raise RoleCommandError("unsupported command")
    operation_id = _canonical_uuid(payload.get("operation_id"), "operation_id")
    frame_request_id = _canonical_uuid(request_id, "request_id")
    if frame_request_id != operation_id:
        raise RoleCommandError("request_id and operation_id mismatch")
    if payload.get("device_id") != LAB1_DEVICE_ID:
        raise RoleCommandError("wrong device_id")
    requested_role = str(payload.get("requested_role") or "").upper()
    if requested_role not in ALLOWED_ROLES:
        raise RoleCommandError("unsupported requested_role")
    if payload.get("simulation_required") is not True:
        raise RoleCommandError("simulation_required must be true")
    _validate_safe_state(state)
    history = _history(state)
    requested_record = _operation_record(payload, operation_id)
    existing_record = history.get(operation_id)
    if existing_record is not None:
        if existing_record != requested_record:
            raise RoleCommandError("duplicate operation_id conflicts with prior request")
        return {
            "ok": True,
            "accepted": True,
            "duplicate": True,
            "operation_id": operation_id,
            "lab_role": state.get("role", "UNASSIGNED"),
            "simulation": True,
            "physical_outputs_enabled": False,
        }
    state["role"] = requested_role
    history[operation_id] = requested_record
    if len(history) > 50:
        for key in list(history)[:-50]:
            history.pop(key, None)
    return {
        "ok": True,
        "accepted": True,
        "operation_id": operation_id,
        "lab_role": requested_role,
        "simulation": True,
        "physical_outputs_enabled": False,
    }


def handle_command_file(state_path: Path, payload_path: Path) -> dict[str, Any]:
    state = load_state(state_path)
    frame = json.loads(payload_path.read_text())
    if frame.get("type") == "command":
        payload = frame.get("payload") or {}
        request_id = frame.get("request_id")
    else:
        payload = frame
        request_id = frame.get("request_id")
    response = apply_role_command(state, payload, request_id=request_id)
    save_state_atomic(state_path, state)
    return response


def heartbeat_state(state: dict[str, Any], registered_module_type: str) -> dict[str, Any]:
    return {
        "lab_role": state.get("role", "UNASSIGNED"),
        "registered_module_type": registered_module_type,
        "simulation": True,
        "physical_outputs_enabled": False,
        "commissioned_local": bool(state.get("commissioned", False)),
        "emergency_ui": {
            "enabled": True,
            "available": True,
            "protocol": "http",
            "port": 6010,
            "config_path": "/config",
            "health_path": "/health",
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply one LAB1 role command JSON file safely.")
    parser.add_argument("--state", default="/opt/homecontrol-lab/state/module.json")
    parser.add_argument("payload")
    args = parser.parse_args()
    print(json.dumps(handle_command_file(Path(args.state), Path(args.payload)), indent=2, sort_keys=True))
