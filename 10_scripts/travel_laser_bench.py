#!/usr/bin/env python3
"""Guarded, reversible Travel_Laser touchscreen bench workflow.

Only ``preflight`` and ``stage`` are non-disruptive. ``test`` requires an
explicit handover flag because it temporarily stops the existing Travel Laser
UI service. ``restore`` only cleans up UI-test processes and restores the
recorded service state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys


TARGET = "laser"
REMOTE_ROOT = "/tmp/homecontrol-touchscreen-test"
REMOTE_STATE = "/tmp/homecontrol-touchscreen-bench-state.json"
REMOTE_LOG = "/tmp/homecontrol-touchscreen-test.log"
REMOTE_PYTHON = "/tmp/homecontrol-touchscreen-venv/bin/python"
REMOTE_PYTHONPATH = "/opt/travel-laser-controller/.venv/lib/python3.13/site-packages"
READ_ONLY_CHECKS = {
    "identity": "hostname; uname -a; cat /etc/os-release",
    "devices": "for p in /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1 /dev/uinput; do printf '%s ' \"$p\"; test -e \"$p\" && echo present || echo missing; done",
    "service": "systemctl is-active travel-laser-ui.service || true; systemctl is-enabled travel-laser-ui.service || true; systemctl show -p MainPID travel-laser-ui.service",
    "processes": "pgrep -af 'travel-laser-ui|chromium|homecontrol-touchscreen' || true",
    "owners": "fuser -v /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1 /dev/uinput 2>&1 || true",
    "resources": "free -h; df -h / /tmp",
    "dependencies": "printf 'chromium='; command -v chromium || echo missing; /opt/travel-laser-controller/.venv/bin/python - <<'PY'\nfor name in ('spidev', 'gpiod', 'smbus2', 'evdev', 'PIL', 'websocket'):\n    try:\n        __import__(name); print(name + '=available')\n    except Exception:\n        print(name + '=missing')\nPY\nprintf 'uinput='; stat -c 'mode=%a owner=%U group=%G' /dev/uinput 2>/dev/null || echo missing",
}


def ssh_command(target: str, command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ssh", target, "--", command], text=True, capture_output=True, check=check)


def remote_status(target: str = TARGET) -> subprocess.CompletedProcess[str]:
    command = (
        "printf 'service='; systemctl is-active travel-laser-ui.service || true; "
        "printf ' enabled='; systemctl is-enabled travel-laser-ui.service || true; echo; "
        "printf 'processes\\n'; pgrep -af 'homecontrol-touchscreen-test|touchscreen_app|touchscreen_display_bridge|chromium' || true; "
        "printf 'owners\\n'; fuser -v /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1 /dev/uinput 2>&1 || true; "
        "printf 'api\\n'; curl -fsS http://127.0.0.1:8765/api/touchscreen/state?role=SIM 2>/dev/null || true; echo"
    )
    return ssh_command(target, command, check=False)


def _state_for_start(target: str) -> dict[str, object]:
    existing = ssh_command(target, f"cat {REMOTE_STATE}", check=False)
    if existing.returncode == 0:
        return json.loads(existing.stdout)
    results = run_preflight(target)
    if not preflight_ok(results):
        raise SystemExit("read-only preflight failed; no service was stopped")
    service_lines = str(results["service"]["stdout"]).splitlines()
    state = {
        "service_active": "active" if any(line.strip() == "active" for line in service_lines) else "inactive",
        "service_enabled": "enabled" if any(line.strip() == "enabled" for line in service_lines) else "disabled",
    }
    state_json = json.dumps(state, separators=(",", ":"))
    ssh_command(target, f"printf '%s' {shlex.quote(state_json)} > {REMOTE_STATE}")
    return state


def _start_command(role: str, remote_root: str) -> str:
    return (
        f"nohup setsid env PYTHONPATH={REMOTE_PYTHONPATH} {REMOTE_PYTHON} {remote_root}/10_scripts/touchscreen_app.py > {REMOTE_LOG} 2>&1 & app=$!; "
        f"nohup setsid sudo -n env HOMECONTROL_TOUCH_LOG=/tmp/homecontrol-touchscreen-events.log PYTHONPATH={REMOTE_PYTHONPATH} {REMOTE_PYTHON} {remote_root}/10_scripts/touchscreen_display_bridge.py --role {shlex.quote(role)} --mode orange_pi >> {REMOTE_LOG} 2>&1 & "
        f"sleep 1; bridge=; for candidate in $(pgrep -f {shlex.quote(remote_root + '/10_scripts/touchscreen_display_bridge.py')} || true); do "
        "if test \"$candidate\" != \"$$\"; then bridge=$(ps -o pgid= -p \"$candidate\" | tr -d ' '); test -n \"$bridge\" && break; fi; done; "
        "test -n \"$bridge\" || { echo 'bridge process group was not found' >&2; exit 1; }; "
        "printf '%s\\n%s\\n' \"$app\" \"$bridge\" > /tmp/homecontrol-touchscreen-test.pids"
    )


def _stop_command(bridge_only: bool = False) -> str:
    if bridge_only:
        return (
            "if test -s /tmp/homecontrol-touchscreen-test.pids; then bridge=$(sed -n '2p' /tmp/homecontrol-touchscreen-test.pids); "
            "sudo -n kill -TERM -- -\"$bridge\" 2>/dev/null || true; fi"
        )
    return (
        "if test -s /tmp/homecontrol-touchscreen-test.pids; then app=$(head -1 /tmp/homecontrol-touchscreen-test.pids); bridge=$(sed -n '2p' /tmp/homecontrol-touchscreen-test.pids); "
        "sudo -n kill -TERM -- -\"$bridge\" 2>/dev/null || true; sudo -n kill -TERM \"$app\" 2>/dev/null || true; sleep 2; "
        "sudo -n kill -KILL -- -\"$bridge\" 2>/dev/null || true; sudo -n kill -KILL \"$app\" 2>/dev/null || true; fi; rm -f /tmp/homecontrol-touchscreen-test.pids"
    )


def start_handover(target: str, role: str) -> None:
    results = run_preflight(target)
    if not preflight_ok(results) or not dependencies_ready(results):
        raise SystemExit("preflight or renderer dependency check failed; no process was started")
    _state_for_start(target)
    existing = ssh_command(target, "test -s /tmp/homecontrol-touchscreen-test.pids", check=False)
    if existing.returncode == 0:
        raise SystemExit("HomeControl bench already has recorded processes; use restart or switch-role")
    for executable in ("touchscreen_app.py", "touchscreen_display_bridge.py"):
        path = f"{REMOTE_ROOT}/10_scripts/{executable}"
        running = ssh_command(target, f"for pid in $(pgrep -f {shlex.quote(path)} || true); do test \"$pid\" != \"$$\" && echo \"$pid\"; done", check=False)
        if running.stdout.strip():
            raise SystemExit(f"HomeControl process already running ({executable}); use stop or restart")
    owners = ssh_command(target, "fuser -s /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1", check=False)
    if owners.returncode == 0:
        raise SystemExit("display or touch device is already owned; no process was started")
    ssh_command(target, "sudo -n systemctl stop travel-laser-ui.service")
    ssh_command(target, _start_command(role, REMOTE_ROOT))
    print(remote_status(target).stdout)


def stop_handover(target: str) -> None:
    ssh_command(target, _stop_command())
    print(remote_status(target).stdout)


def switch_role(target: str, role: str) -> None:
    ssh_command(target, _stop_command(bridge_only=True))
    ssh_command(target, (
        f"nohup setsid sudo -n env HOMECONTROL_TOUCH_LOG=/tmp/homecontrol-touchscreen-events.log PYTHONPATH={REMOTE_PYTHONPATH} {REMOTE_PYTHON} {REMOTE_ROOT}/10_scripts/touchscreen_display_bridge.py --role {shlex.quote(role)} --mode orange_pi >> {REMOTE_LOG} 2>&1 & "
        "sleep 1; bridge=; for candidate in $(pgrep -f /tmp/homecontrol-touchscreen-test/10_scripts/touchscreen_display_bridge.py || true); do "
        "if test \"$candidate\" != \"$$\"; then bridge=$(ps -o pgid= -p \"$candidate\" | tr -d ' '); test -n \"$bridge\" && break; fi; done; "
        "test -n \"$bridge\" || { echo 'bridge process group was not found' >&2; exit 1; }; app=$(head -1 /tmp/homecontrol-touchscreen-test.pids); printf '%s\\n%s\\n' \"$app\" \"$bridge\" > /tmp/homecontrol-touchscreen-test.pids"
    ))
    print(remote_status(target).stdout)


def run_preflight(target: str = TARGET) -> dict[str, dict[str, object]]:
    results = {}
    for name, command in READ_ONLY_CHECKS.items():
        completed = ssh_command(target, command, check=False)
        results[name] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    results["manual"] = {
        "returncode": 0,
        "stdout": "Confirm the laser is physically disconnected before test handover; SSH cannot prove this.",
        "stderr": "",
    }
    return results


def preflight_ok(results: dict[str, dict[str, object]]) -> bool:
    return all(int(item["returncode"]) == 0 for name, item in results.items() if name != "manual")


def dependencies_ready(results: dict[str, dict[str, object]]) -> bool:
    output = str(results.get("dependencies", {}).get("stdout", ""))
    return all(marker in output for marker in ("chromium=/usr", "PIL=available", "websocket=available"))


def restore_commands(state: dict[str, object]) -> list[str]:
    commands = [
        "if test -s /tmp/homecontrol-touchscreen-test.pids; then while read -r pid; do sudo -n kill -TERM \"$pid\" 2>/dev/null || true; sudo -n pkill -TERM -P \"$pid\" 2>/dev/null || true; done < /tmp/homecontrol-touchscreen-test.pids; sleep 2; while read -r pid; do sudo -n kill -KILL \"$pid\" 2>/dev/null || true; sudo -n pkill -KILL -P \"$pid\" 2>/dev/null || true; done < /tmp/homecontrol-touchscreen-test.pids; fi",
        "rm -f /tmp/homecontrol-touchscreen-test.pids",
    ]
    if state.get("service_active") == "active":
        commands.append("sudo -n systemctl start travel-laser-ui.service")
    else:
        commands.append("sudo -n systemctl stop travel-laser-ui.service || true")
    if state.get("service_enabled") == "enabled":
        commands.append("sudo -n systemctl enable travel-laser-ui.service")
    else:
        commands.append("sudo -n systemctl disable travel-laser-ui.service || true")
    commands.append(f"rm -f {REMOTE_STATE}")
    return commands


def stage(source_root: Path, target: str, remote_root: str) -> None:
    files = [
        "10_scripts/touchscreen_app.py",
        "10_scripts/touchscreen_display_bridge.py",
        "10_scripts/touchscreen_hardware",
        "10_scripts/touchscreen_ui",
        "06_config/01_HCM/hardware_pins.yaml",
        "06_config/02_SIM/hardware_pins.yaml",
        "06_config/03_LCM/hardware_pins.yaml",
        "06_config/04_RCM/hardware_pins.yaml",
        "07_servises/common",
    ]
    ssh_command(target, f"rm -rf {shlex.quote(remote_root)} && mkdir -p {shlex.quote(remote_root)}")
    for relative in files:
        source = source_root / relative
        destination = f"{target}:{remote_root}/{relative}"
        ssh_command(target, f"mkdir -p {shlex.quote(str(Path(remote_root) / Path(relative).parent))}")
        subprocess.run(["scp", "-r", str(source), destination], check=True)


def test_handover(target: str, remote_root: str, role: str, dry_run: bool = False) -> None:
    results = run_preflight(target)
    if not preflight_ok(results):
        raise SystemExit("read-only preflight failed; no service was stopped")
    if dry_run:
        print(json.dumps({
            "dry_run": True,
            "role": role,
            "remote_root": remote_root,
            "dependencies_ready": dependencies_ready(results),
            "would_stop": "travel-laser-ui.service",
            "would_start": ["touchscreen_app.py", "touchscreen_display_bridge.py"],
            "would_restore": restore_commands({"service_active": "active", "service_enabled": "enabled"}),
        }, indent=2))
        return
    if not sys.argv or "--approve-hardware-handover" not in sys.argv:
        raise SystemExit("test mode requires --approve-hardware-handover")
    start_handover(target, role)
    print(json.dumps({"log": REMOTE_LOG, "restore": "python3 10_scripts/travel_laser_bench.py restore"}, indent=2))


def restore(target: str) -> None:
    state_result = ssh_command(target, f"cat {REMOTE_STATE}", check=False)
    if state_result.returncode != 0:
        raise SystemExit("No recorded bench state found on the target")
    state = json.loads(state_result.stdout)
    ssh_command(target, "; ".join(restore_commands(state)))
    print("Travel Laser UI test resources released and recorded service state restored.")


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeControl Travel Laser bench workflow")
    parser.add_argument("command", choices=["preflight", "stage", "test", "status", "start", "stop", "restart", "switch-role", "restore"])
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote-root", default=REMOTE_ROOT)
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--approve-hardware-handover", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "preflight":
        results = run_preflight(args.target)
        print(json.dumps(results, indent=2))
        if not preflight_ok(results):
            raise SystemExit(1)
    elif args.command == "stage":
        stage(args.source_root, args.target, args.remote_root)
        print(f"Staged HomeControl touchscreen files at {args.target}:{args.remote_root}; no service was stopped.")
    elif args.command == "test":
        test_handover(args.target, args.remote_root, args.role, args.dry_run)
    elif args.command == "status":
        print(remote_status(args.target).stdout)
    elif args.command == "start":
        start_handover(args.target, args.role)
    elif args.command == "stop":
        stop_handover(args.target)
    elif args.command == "restart":
        stop_handover(args.target)
        start_handover(args.target, args.role)
    elif args.command == "switch-role":
        switch_role(args.target, args.role)
    else:
        restore(args.target)


if __name__ == "__main__":
    main()
