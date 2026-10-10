#!/usr/bin/python3
"""HCM application watchdog. Compatible with host Python 3.6.

Monitors HCM through its Docker bridge instead of Jetson's published WLAN port.
Does not control PostgreSQL or independent Unified Heartbeat V3.
"""
import fcntl
import json
import os
import subprocess
import sys
import time

STATE_DIR = "/var/lib/hcm-watchdog"
STATE_FILE = STATE_DIR + "/state.json"
LOCK_FILE = "/run/lock/hcm-watchdog.lock"

MAX_FAILURES = 3
MAX_RESTARTS = 3
RESTART_WINDOW = 900  # 15 minutes
CHECK_ONLY = "--check-only" in sys.argv


def command(args, timeout=10):
    return subprocess.check_output(
        args, stderr=subprocess.DEVNULL, timeout=timeout
    ).decode().strip()


def active(service):
    try:
        return command(["systemctl", "is-active", service]) == "active"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def healthy():
    try:
        ip = command([
            "docker", "inspect", "hcm-test",
            "--format",
            '{{(index .NetworkSettings.Networks "hcm-control").IPAddress}}'
        ])

        if not ip:
            return False

        code = command([
            "curl", "--noproxy", "*",
            "-sS", "-o", "/dev/null",
            "-w", "%{http_code}",
            "--connect-timeout", "2",
            "--max-time", "5",
            "http://{}:8080/".format(ip)
        ])

        return code == "200"
    except (subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError):
        return False


def load_state():
    try:
        with open(STATE_FILE) as file:
            return json.load(file)
    except (IOError, ValueError):
        return {"failures": 0, "restarts": []}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as file:
        json.dump(state, file)
    os.rename(tmp, STATE_FILE)


def log(message):
    print("HCM WATCHDOG: " + message, flush=True)


def main():
    os.makedirs(STATE_DIR, exist_ok=True)

    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return

        # An intentional systemd administrative stop disables recovery.
        if not active("hcm.service"):
            log("HCM systemd service inactive; recovery suppressed")
            return

        if not active("hcm-postgres.service"):
            log("PostgreSQL service inactive; recovery suppressed")
            return

        result = healthy()

        if CHECK_ONLY:
            log("Health check: {}".format(
                "HEALTHY" if result else "FAILED"
            ))
            return

        state = load_state()
        now = int(time.time())

        state["restarts"] = [
            t for t in state.get("restarts", [])
            if now - t < RESTART_WINDOW
        ]

        if result:
            if state.get("failures", 0):
                log("HCM healthy; failure counter cleared")
            state["failures"] = 0
            save_state(state)
            return

        state["failures"] = state.get("failures", 0) + 1
        log("Health failure {}/{}".format(
            state["failures"], MAX_FAILURES
        ))

        if state["failures"] < MAX_FAILURES:
            save_state(state)
            return

        if len(state["restarts"]) >= MAX_RESTARTS:
            log("ALERT: Recovery limit reached (3 in 15 minutes)")
            save_state(state)
            return

        # Recheck service state to reduce maintenance-stop races.
        if not active("hcm.service") or not active("hcm-postgres.service"):
            log("Recovery cancelled; prerequisite no longer active")
            save_state(state)
            return

        state["restarts"].append(now)
        state["failures"] = 0
        save_state(state)

        log("Attempting HCM-only systemd restart")

        try:
            subprocess.check_call(
                ["systemctl", "restart", "hcm.service"],
                timeout=120
            )
            log("Restart command completed; awaiting health check")
        except (subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            log("ALERT: HCM restart command failed")


if __name__ == "__main__":
    main()
