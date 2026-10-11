#!/usr/bin/env python3
"""LAB1 simulation role helper for manual deployment.

This file is intentionally repository-delivered only. Codex must not install it
on LAB1 automatically. The helper contains no private keys and performs no
network, hostname, GPIO, relay, dimmer, CAN, I2C, SPI or VLAN changes.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


LAB1_DEVICE_ID = "2ccf675d3414"
ALLOWED_ROLES = {"UNASSIGNED", "RCM", "SIM", "LCM"}


class RoleCommandError(ValueError):
    pass


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "device_id": LAB1_DEVICE_ID,
            "lab_role": "UNASSIGNED",
            "simulation": True,
            "physical_outputs_enabled": False,
            "applied_operations": [],
        }
    return json.loads(path.read_text())


def save_state_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as tmp:
            json.dump(state, tmp, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def apply_role_command(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("op") != "set_module_role":
        raise RoleCommandError("unsupported command")
    operation_id = str(payload.get("operation_id") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", operation_id):
        raise RoleCommandError("invalid operation_id")
    if payload.get("device_id") != LAB1_DEVICE_ID:
        raise RoleCommandError("wrong device_id")
    requested_role = str(payload.get("requested_role") or "").upper()
    if requested_role not in ALLOWED_ROLES:
        raise RoleCommandError("unsupported requested_role")
    if payload.get("simulation_required") is not True:
        raise RoleCommandError("simulation_required must be true")
    applied = list(state.get("applied_operations") or [])
    if operation_id in applied:
        return {
            "ok": True,
            "accepted": True,
            "duplicate": True,
            "operation_id": operation_id,
            "lab_role": state.get("lab_role", "UNASSIGNED"),
            "simulation": True,
            "physical_outputs_enabled": False,
        }
    state["device_id"] = LAB1_DEVICE_ID
    state["lab_role"] = requested_role
    state["simulation"] = True
    state["physical_outputs_enabled"] = False
    state["commissioned_local"] = False
    applied.append(operation_id)
    state["applied_operations"] = applied[-50:]
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
    payload = json.loads(payload_path.read_text())
    response = apply_role_command(state, payload)
    save_state_atomic(state_path, state)
    return response


def heartbeat_state(state: dict[str, Any], registered_module_type: str) -> dict[str, Any]:
    return {
        "lab_role": state.get("lab_role", "UNASSIGNED"),
        "registered_module_type": registered_module_type,
        "simulation": True,
        "physical_outputs_enabled": False,
        "commissioned_local": False,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply one LAB1 role command JSON file safely.")
    parser.add_argument("--state", default="/opt/homecontrol-lab/state/module.json")
    parser.add_argument("payload")
    args = parser.parse_args()
    print(json.dumps(handle_command_file(Path(args.state), Path(args.payload)), indent=2, sort_keys=True))
