#!/usr/bin/env python3
"""Add the authenticated user-snapshot handler to the deployed LAB1 agent."""
from pathlib import Path
import os
import tempfile

TARGET = Path("/opt/homecontrol-lab/lab_agent.py")
IMPORT = "from lab1_user_sync import active_module_type, apply_config_payload, apply_module_config_payload\n"
INITIAL = "        if reply.get(\"type\") != \"config\":\n            raise RuntimeError(\n                \"HCM did not return config; assignment refused\"\n            )\n"
INITIAL_REPLACEMENT = INITIAL + "\n        initial_payload = reply.get(\"payload\") or {}\n        apply_config_payload(initial_payload)\n        apply_module_config_payload(initial_payload)\n"
INITIAL_SYNC = "        apply_config_payload(reply.get(\"payload\") or {})\n"
LOOP = "                if kind == \"heartbeat_ack\":\n                    break\n"
LOOP_REPLACEMENT = "                if kind == \"config\":\n                    config_payload = response.get(\"payload\") or {}\n                    user_applied = apply_config_payload(config_payload)\n                    config_result = apply_module_config_payload(config_payload)\n                    await send_frame(writer, \"command_ack\", {\"ok\": config_result.get(\"ok\", True), \"user_sync\": user_applied, \"config_sync\": config_result}, response.get(\"request_id\"))\n                    continue\n\n" + LOOP
DUPLICATE_LOOP = LOOP_REPLACEMENT + LOOP_REPLACEMENT


def main() -> None:
    text = TARGET.read_text()
    text = text.replace("from lab1_user_sync import apply_config_payload\n", IMPORT)
    if IMPORT not in text:
        marker = "from pathlib import Path\n"
        if marker not in text:
            raise SystemExit("LAB1 agent import anchor not found")
        text = text.replace(marker, marker + IMPORT, 1)
    if "apply_module_config_payload(initial_payload)" not in text:
        if text.count(INITIAL_SYNC) != 1:
            raise SystemExit("LAB1 agent initial config sync anchor did not match exactly")
        text = text.replace(INITIAL_SYNC, "        initial_payload = reply.get(\"payload\") or {}\n        apply_config_payload(initial_payload)\n        apply_module_config_payload(initial_payload)\n", 1)
    if "config_result = apply_module_config_payload(config_payload)" not in text:
        text = text.replace(DUPLICATE_LOOP, LOOP_REPLACEMENT)
        if "config_result = apply_module_config_payload(config_payload)" not in text:
            if text.count(LOOP) != 1:
                raise SystemExit("LAB1 agent config loop anchor did not match exactly")
            text = text.replace(LOOP, LOOP_REPLACEMENT, 1)
    while text.count(LOOP_REPLACEMENT) > 1:
        text = text.replace(LOOP_REPLACEMENT + LOOP_REPLACEMENT, LOOP_REPLACEMENT, 1)
    text = text.replace('"module_type": "RCM",', '"module_type": active_module_type(),')
    text = text.replace('"registered_module_type": "LCM",', '"registered_module_type": active_module_type(),')
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
