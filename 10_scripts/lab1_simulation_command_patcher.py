#!/usr/bin/env python3
"""Add the explicitly software-only relay command to the LAB1 simulation agent."""

from pathlib import Path
import os
import tempfile


TARGET = Path('/opt/homecontrol-lab/lab_agent.py')
MARKER = 'if payload.get("op") == "simulate_relay":'
OLD = '''            await send_frame(
                writer,
                "command_ack",
                {
                    "ok": False,
                    "error": "simulation_commands_disabled",
                },
                request_id,
            )
            print("HCM command rejected: simulation-only", flush=True)
            continue'''
NEW = '''            if payload.get("op") == "simulate_relay":
                from lab1_role_agent import RoleCommandError, load_state, save_state_atomic

                try:
                    if payload.get("simulation") is not True:
                        raise RoleCommandError("simulation flag is required")
                    if payload.get("physical_outputs_enabled") is not False:
                        raise RoleCommandError("physical outputs must remain disabled")
                    channel = str(payload.get("channel") or "").upper()
                    if not channel:
                        raise RoleCommandError("channel is required")
                    state_path = getattr(context, "state_path", Path("/opt/homecontrol-lab/state/module.json"))
                    state = load_state(state_path)
                    if state.get("simulation") is not True or state.get("physical_outputs_enabled") is not False:
                        raise RoleCommandError("LAB1 safety state is not simulation-only")
                    simulated_relays = state.setdefault("simulated_relays", {})
                    simulated_relays[channel] = bool(payload.get("value"))
                    save_state_atomic(state_path, state)
                    ack = {
                        "ok": True,
                        "channel": channel,
                        "value": simulated_relays[channel],
                        "simulation": True,
                        "physical_outputs_commanded": False,
                        "state_confidence": "simulated_commanded_only",
                    }
                except (RoleCommandError, KeyError, TypeError, ValueError) as exc:
                    ack = {
                        "ok": False,
                        "error": str(exc),
                        "simulation": True,
                        "physical_outputs_commanded": False,
                    }
                await send_frame(writer, "command_ack", ack, request_id)
                continue
            await send_frame(
                writer,
                "command_ack",
                {
                    "ok": False,
                    "error": "simulation_commands_disabled",
                },
                request_id,
            )
            print("HCM command rejected: simulation-only", flush=True)
            continue'''


def main() -> None:
    text = TARGET.read_text()
    if MARKER in text:
        return
    if text.count(OLD) != 1:
        raise SystemExit('LAB1 simulation rejection block did not match exactly')
    updated = text.replace(OLD, NEW, 1)
    mode = TARGET.stat().st_mode & 0o777
    fd, name = tempfile.mkstemp(prefix='.lab_agent.', dir=str(TARGET.parent))
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, TARGET)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
