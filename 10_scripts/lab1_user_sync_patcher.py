#!/usr/bin/env python3
"""Add the authenticated user-snapshot handler to the deployed LAB1 agent."""
from pathlib import Path
import os
import tempfile

TARGET = Path("/opt/homecontrol-lab/lab_agent.py")
IMPORT = "from lab1_user_sync import apply_config_payload\n"
INITIAL = "        if reply.get(\"type\") != \"config\":\n            raise RuntimeError(\n                \"HCM did not return config; assignment refused\"\n            )\n"
INITIAL_REPLACEMENT = INITIAL + "\n        apply_config_payload(reply.get(\"payload\") or {})\n"
LOOP = "                if kind == \"heartbeat_ack\":\n                    break\n"
LOOP_REPLACEMENT = "                if kind == \"config\":\n                    applied = apply_config_payload(response.get(\"payload\") or {})\n                    await send_frame(writer, \"command_ack\", {\"ok\": True, \"user_sync\": applied}, response.get(\"request_id\"))\n                    continue\n\n" + LOOP


def main() -> None:
    text = TARGET.read_text()
    if IMPORT not in text:
        marker = "from pathlib import Path\n"
        if marker not in text:
            raise SystemExit("LAB1 agent import anchor not found")
        text = text.replace(marker, marker + IMPORT, 1)
    if "apply_config_payload(reply.get(\"payload\") or {})" not in text:
        if text.count(INITIAL) != 1:
            raise SystemExit("LAB1 agent initial config block did not match exactly")
        text = text.replace(INITIAL, INITIAL_REPLACEMENT, 1)
    if "if kind == \"config\":\n                    apply_config_payload" not in text:
        if text.count(LOOP) != 1:
            raise SystemExit("LAB1 agent config loop anchor did not match exactly")
        text = text.replace(LOOP, LOOP_REPLACEMENT, 1)
    mode = TARGET.stat().st_mode & 0o777
    fd, name = tempfile.mkstemp(prefix=".lab_agent.", dir=str(TARGET.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, TARGET)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
