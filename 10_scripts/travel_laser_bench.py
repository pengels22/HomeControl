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
READ_ONLY_CHECKS = {
    "identity": "hostname; uname -a; cat /etc/os-release",
    "devices": "for p in /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1 /dev/uinput; do printf '%s ' \"$p\"; test -e \"$p\" && echo present || echo missing; done",
    "service": "systemctl is-active travel-laser-ui.service || true; systemctl is-enabled travel-laser-ui.service || true; systemctl show -p MainPID travel-laser-ui.service",
    "processes": "pgrep -af 'travel-laser-ui|chromium|homecontrol-touchscreen' || true",
    "owners": "fuser -v /dev/spidev1.1 /dev/i2c-2 /dev/gpiochip1 /dev/uinput 2>&1 || true",
}


def ssh_command(target: str, command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ssh", target, "--", command], text=True, capture_output=True, check=check)


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


def restore_commands(state: dict[str, object]) -> list[str]:
    commands = [
        "if test -s /tmp/homecontrol-touchscreen-test.pids; then xargs -r kill < /tmp/homecontrol-touchscreen-test.pids || true; fi",
        "rm -f /tmp/homecontrol-touchscreen-test.pids",
    ]
    if state.get("service_active") == "active":
        commands.append("systemctl start travel-laser-ui.service")
    else:
        commands.append("systemctl stop travel-laser-ui.service || true")
    if state.get("service_enabled") == "enabled":
        commands.append("systemctl enable travel-laser-ui.service")
    else:
        commands.append("systemctl disable travel-laser-ui.service || true")
    commands.append(f"rm -f {REMOTE_STATE}")
    return commands


def stage(source_root: Path, target: str, remote_root: str) -> None:
    files = [
        "10_scripts/touchscreen_app.py",
        "10_scripts/touchscreen_display_bridge.py",
        "10_scripts/touchscreen_hardware",
        "10_scripts/touchscreen_ui",
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


def test_handover(target: str, remote_root: str, role: str) -> None:
    if not sys.argv or "--approve-hardware-handover" not in sys.argv:
        raise SystemExit("test mode requires --approve-hardware-handover")
    results = run_preflight(target)
    service_lines = str(results["service"]["stdout"]).splitlines()
    state = {
        "service_active": "active" if "active" in service_lines else "inactive",
        "service_enabled": "enabled" if "enabled" in service_lines else "disabled",
        "role": role,
        "remote_root": remote_root,
    }
    state_json = json.dumps(state, separators=(",", ":"))
    ssh_command(target, f"printf '%s' {shlex.quote(state_json)} > {REMOTE_STATE}")
    ssh_command(target, "systemctl stop travel-laser-ui.service")
    launch = (
        f"nohup python3 {remote_root}/10_scripts/touchscreen_app.py > {REMOTE_LOG} 2>&1 & "
        f"echo $! > /tmp/homecontrol-touchscreen-test.pids; "
        f"nohup python3 {remote_root}/10_scripts/touchscreen_display_bridge.py --role {shlex.quote(role)} --mode orange_pi >> {REMOTE_LOG} 2>&1 & "
        f"echo $! >> /tmp/homecontrol-touchscreen-test.pids"
    )
    ssh_command(target, launch)
    print(json.dumps({"state": state, "log": REMOTE_LOG, "restore": "python3 10_scripts/travel_laser_bench.py restore"}, indent=2))


def restore(target: str) -> None:
    state_result = ssh_command(target, f"cat {REMOTE_STATE}", check=False)
    if state_result.returncode != 0:
        raise SystemExit("No recorded bench state found on the target")
    state = json.loads(state_result.stdout)
    ssh_command(target, "; ".join(restore_commands(state)))
    print("Travel Laser UI test resources released and recorded service state restored.")


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeControl Travel Laser bench workflow")
    parser.add_argument("command", choices=["preflight", "stage", "test", "restore"])
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote-root", default=REMOTE_ROOT)
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--approve-hardware-handover", action="store_true")
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
        test_handover(args.target, args.remote_root, args.role)
    else:
        restore(args.target)


if __name__ == "__main__":
    main()
