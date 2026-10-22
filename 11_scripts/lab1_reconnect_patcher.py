#!/usr/bin/env python3
"""Add immediate state reconciliation to the installed LAB1 simulation agent."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


TARGET = Path("/opt/homecontrol-lab/lab_agent.py")
SNAPSHOT_MARKER = 'await send_frame(writer, "state", {'
INITIAL_CONFIG = "        apply_module_config_payload(initial_payload)\n"
ACK_MARKER = '                if kind == "heartbeat_ack":\n'
RELAY_MARKER = '                    "commissioned_local": False,\n'


def apply(path: Path = TARGET) -> None:
    source = path.read_text()
    if SNAPSHOT_MARKER in source:
        if source.count(SNAPSHOT_MARKER) != 1:
            raise SystemExit("LAB1 reconnect snapshot marker is not unique")
        return
    for marker in (INITIAL_CONFIG, ACK_MARKER, RELAY_MARKER):
        if source.count(marker) != 1:
            raise SystemExit(f"LAB1 reconnect anchor did not match exactly: {marker.strip()}")
    snapshot = '''        from lab1_role_agent import heartbeat_state
        snapshot_state = verified_state()
        await send_frame(writer, "state", {
            "module_uuid": MODULE_UUID,
            "device_id": DEVICE_ID,
            "hostname": "lab1",
            "ts": time.time(),
            "state": heartbeat_state(snapshot_state, active_module_type()),
            "faults": {},
        }, str(uuid.uuid4()))

'''
    updated = source.replace(INITIAL_CONFIG, INITIAL_CONFIG + "\n" + snapshot, 1)
    updated = updated.replace(
        ACK_MARKER,
        '                if kind == "state_ack":\n                    continue\n\n' + ACK_MARKER,
        1,
    )
    updated = updated.replace(
        RELAY_MARKER,
        RELAY_MARKER + '                    "simulated_relays": state.get("simulated_relays", {}),\n',
        1,
    )
    mode = path.stat().st_mode & 0o777
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    apply()
