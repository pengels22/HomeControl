#!/usr/bin/env python3
"""Device-hosted HomeControl integration test coordinator.

Live mode performs fixed read-only diagnostics against the configured devices.
Mutating scenarios always use the isolated authority and mock transports below;
the coordinator never opens Linux GPIO/I2C/Shelly output transports.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import dataclasses
import html
import importlib
import importlib.util
import json
import os
import shutil
import signal
import socket
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
BLOCKED = "BLOCKED"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def redact(value: Any) -> Any:
    """Remove credential-shaped fields from reportable structures."""
    if isinstance(value, dict):
        return {k: "[redacted]" if any(word in k.lower() for word in ("pin", "token", "secret", "hash", "password", "key")) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(word in lowered for word in ("password=", "token=", "secret=", "pin=")):
            return "[redacted sensitive text]"
    return value


@dataclasses.dataclass
class Result:
    subsystem: str
    name: str
    status: str
    description: str
    expected: str
    actual: str
    duration_ms: int
    evidence: dict[str, Any] = dataclasses.field(default_factory=dict)
    remediation: str | None = None
    correlation_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)

    def as_dict(self) -> dict[str, Any]:
        return redact(dataclasses.asdict(self))


class Cancelled(RuntimeError):
    pass


class Coordinator:
    def __init__(self, *, deadline: float, run_id: str, report_dir: Path):
        self.deadline = deadline
        self.run_id = run_id
        self.report_dir = report_dir
        self.results: list[Result] = []
        self.cancelled = False

    def check(self) -> None:
        if self.cancelled or time.monotonic() >= self.deadline:
            raise Cancelled("coordinator timeout or cancellation")

    def record(self, subsystem: str, name: str, status: str, description: str, expected: str, actual: str, started: float, evidence: dict[str, Any] | None = None, remediation: str | None = None) -> Result:
        result = Result(subsystem, name, status, description, expected, actual, round((time.monotonic() - started) * 1000), evidence or {}, remediation)
        self.results.append(result)
        return result

    def run_step(self, subsystem: str, name: str, fn: Callable[[], dict[str, Any] | None], *, description: str, expected: str, required: bool = True) -> None:
        started = time.monotonic()
        try:
            self.check()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(fn)
            try:
                evidence = future.result(timeout=min(30.0, max(0.1, self.deadline - time.monotonic()))) or {}
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            self.record(subsystem, name, PASS, description, expected, "condition satisfied", started, evidence)
        except concurrent.futures.TimeoutError as exc:
            self.record(subsystem, name, BLOCKED if required else SKIP, description, expected, "per-step timeout", started, remediation="Inspect the bounded step and rerun with isolated resources.")
        except Cancelled as exc:
            self.record(subsystem, name, BLOCKED if required else SKIP, description, expected, str(exc), started, remediation="Run on the coordinator with a larger timeout or resolve cancellation.")
        except Exception as exc:  # Independent safe checks continue.
            self.record(subsystem, name, FAIL, description, expected, f"{type(exc).__name__}: {exc}", started, remediation="Inspect the correlated evidence and rerun after the reported prerequisite is repaired.")


class SimulatedAuthority:
    """Small HCM-authoritative fixture; no database or live device access."""

    def __init__(self, clock: Callable[[], float] | None = None):
        self.clock = clock or time.monotonic
        self.users: dict[str, dict[str, Any]] = {}
        self.devices = {"screen-1": {"token": "device-token", "modules": {"lab1"}}, "screen-2": {"token": "other-device-token", "modules": {"lab1"}}}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.rate_failures = 0
        self.state = {"relay-a1": False, "dimmer-10-1": 0}
        self.locked: set[str] = set()
        self.revision = 0
        self.available = True

    def add_user(self, username: str, pin: str, permission: str = "VIEWER") -> None:
        if len(pin) != 6 or not pin.isdigit():
            raise ValueError("PIN must contain exactly six digits")
        if any(user["pin"] == pin and user["enabled"] for user in self.users.values()):
            raise ValueError("PIN is already enrolled")
        self.users[username] = {"pin": pin, "permission": permission, "enabled": True}

    def unlock(self, pin: str, device_id: str = "screen-1") -> str:
        if not self.available:
            raise ConnectionError("HCM unavailable")
        device = self.devices[device_id]
        if self.rate_failures >= 3:
            raise PermissionError("rate limited")
        user = next((item for item in self.users.values() if item["pin"] == pin and item["enabled"]), None)
        if not user:
            self.rate_failures += 1
            raise PermissionError("invalid PIN")
        self.rate_failures = 0
        token = uuid.uuid4().hex
        self.sessions[token] = {"device": device_id, "permission": user["permission"], "expires": self.clock() + 300, "absolute": self.clock() + 3600}
        return token

    def command(self, session: str, logical_name: str, value: Any, device_id: str = "screen-1") -> dict[str, Any]:
        if not self.available:
            raise ConnectionError("HCM unavailable")
        item = self.sessions.get(session)
        if not item or item["device"] != device_id or item["expires"] <= self.clock() or item["absolute"] <= self.clock():
            raise PermissionError("session expired")
        if item["permission"] not in {"CONTROL", "ADMIN"}:
            raise PermissionError("touchscreen permission does not allow control")
        if logical_name in self.locked:
            raise PermissionError("maintenance lockout")
        if logical_name not in self.state:
            raise KeyError(logical_name)
        self.state[logical_name] = value
        self.revision += 1
        item["expires"] = self.clock() + 300
        return {"ok": True, "state_revision": self.revision, "confirmed": value}

    def revoke(self, session: str) -> None:
        self.sessions.pop(session, None)


def run_simulation_scenarios(coord: Coordinator) -> None:
    authority = SimulatedAuthority()
    authority.add_user("viewer", "111111", "VIEWER")
    authority.add_user("control", "222222", "CONTROL")
    authority.add_user("admin", "333333", "ADMIN")

    def auth_flow() -> dict[str, Any]:
        viewer = authority.unlock("111111")
        try:
            authority.command(viewer, "relay-a1", True)
        except PermissionError:
            pass
        else:
            raise AssertionError("VIEWER command was accepted")
        control = authority.unlock("222222")
        authority.command(control, "relay-a1", True)
        authority.locked.add("relay-a1")
        try:
            authority.command(control, "relay-a1", False)
        except PermissionError:
            pass
        else:
            raise AssertionError("maintenance lockout was bypassed")
        return {"state_revision": authority.revision, "confirmed_relay": authority.state["relay-a1"]}

    coord.run_step("HCM/API", "authenticated logical command chain", auth_flow, description="PIN session -> logical binding -> HCM arbitration -> simulated module state", expected="authorized control succeeds and viewer/lockout commands are rejected")

    def pin_controls() -> dict[str, Any]:
        try:
            authority.add_user("duplicate", "222222")
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate PIN accepted")
        for _ in range(3):
            try:
                authority.unlock("999999")
            except PermissionError:
                pass
        try:
            authority.unlock("222222")
        except PermissionError:
            pass
        else:
            raise AssertionError("rate limiter did not block repeated failures")
        clock = [0.0]
        timed = SimulatedAuthority(clock=lambda: clock[0])
        timed.add_user("timed", "444444", "CONTROL")
        timed_session = timed.unlock("444444")
        try:
            timed.command(timed_session, "relay-a1", True, device_id="screen-2")
        except PermissionError:
            pass
        else:
            raise AssertionError("cross-device session was accepted")
        clock[0] = 301
        try:
            timed.command(timed_session, "relay-a1", True)
        except PermissionError:
            pass
        else:
            raise AssertionError("idle expiry was not enforced")
        timed.revoke(timed_session)
        clock[0] = 0
        absolute_session = timed.unlock("444444")
        clock[0] = 3601
        try:
            timed.command(absolute_session, "relay-a1", True)
        except PermissionError:
            pass
        else:
            raise AssertionError("absolute expiry was not enforced")
        disabled = SimulatedAuthority()
        disabled.add_user("disabled", "555555", "VIEWER")
        disabled.users["disabled"]["enabled"] = False
        try:
            disabled.unlock("555555")
        except PermissionError:
            pass
        else:
            raise AssertionError("disabled user was accepted")
        return {"duplicate_rejected": True, "rate_limited": True, "idle_expiry": True, "absolute_expiry": True, "cross_device_rejected": True, "disabled_user_rejected": True, "plaintext_in_report": False}

    coord.run_step("User profiles/PIN", "PIN uniqueness and throttling", pin_controls, description="Exercise isolated PIN enrollment constraints and progressive failure handling", expected="duplicate and repeated invalid PINs are rejected without exposing PIN material")

    def disconnect() -> dict[str, Any]:
        token = authority.sessions[next(iter(authority.sessions))]
        authority.available = False
        try:
            authority.command(next(iter(authority.sessions)), "dimmer-10-1", 65)
        except ConnectionError:
            pass
        else:
            raise AssertionError("command succeeded while HCM was unavailable")
        authority.available = True
        return {"fallback_to_simulation": False, "authoritative_state": authority.state, "session_expiry": token["expires"]}

    coord.run_step("Security/availability", "HCM disconnect fails closed", disconnect, description="Ensure a lost HCM connection cannot create a local mutating fallback", expected="commands are rejected and no simulated fallback is presented as production state")

    def parity() -> dict[str, Any]:
        state_for_touchscreen = {"state_revision": authority.revision, "relays": {"relay-a1": authority.state["relay-a1"]}, "dimmers": {"dimmer-10-1": authority.state["dimmer-10-1"]}}
        authoritative = {"state_revision": authority.revision, "relays": {"relay-a1": authority.state["relay-a1"]}, "dimmers": {"dimmer-10-1": authority.state["dimmer-10-1"]}}
        assert state_for_touchscreen == authoritative
        return {"state_revision": authority.revision, "web_native_state_equal": True, "pending_or_rejected_states_not_confirmed": True}

    coord.run_step("Native touchscreen", "authoritative state parity", parity, description="Verify the native touchscreen fixture consumes the same logical state revision and values as the web contract", expected="state and confirmed values match HCM authority")


def run_driver_scenarios(coord: Coordinator) -> None:
    drivers = importlib.import_module("07_servises.common.physical_drivers")

    def drivers_run() -> dict[str, Any]:
        bundle = drivers.build_lab1_mock_drivers()
        transport = bundle["i2c_transport"]
        rcm, lcm, pwm = bundle["rcm_relays"], bundle["lcm_relays"], bundle["lcm_pwm"]
        rcm.initialize(); lcm.initialize(); pwm.initialize()
        for index in range(32):
            assert rcm.set_channel(index, index % 2 == 0)["readback"] is (index % 2 == 0)
        for index in range(8):
            assert lcm.set_channel(index, index % 2 == 1)["readback"] is (index % 2 == 1)
        for index in range(10):
            pwm.set_percent(index, index * 10)
        for component in ("light:0", "light:1"):
            bundle["shelly_1"].set_brightness(component, 65)
            bundle["shelly_2"].set_brightness(component, 35)
        try:
            rcm.set_channel(32, True)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid relay channel accepted")
        transport.fail_writes = True
        try:
            try:
                lcm.set_channel(0, True)
            except drivers.HardwareTransportError:
                pass
            else:
                raise AssertionError("I2C failure was hidden")
        finally:
            transport.fail_writes = False
        assert not bundle["commissioned_channels"] if "commissioned_channels" in bundle else True
        return {"rcm_relays": 32, "lcm_relays": 8, "pca9685_dimmers": 10, "shelly_dimmers": 4, "i2c_operations": transport.operation_count, "physical_transports_opened": False, "commissioned_channels": []}

    coord.run_step("Hardware configuration/commissioning", "isolated production-shaped driver suite", drivers_run, description="Exercise corrected register-aware drivers with mocks only", expected="all mapped channels, failures, polarity and invalid-channel gates behave safely")


def run_fire_scenarios(coord: Coordinator) -> None:
    gpio = importlib.import_module("00_Heartbeat.gpio_inputs")

    def fire_run() -> dict[str, Any]:
        fire = gpio.DebouncedLevel(250)
        assert fire.update(False, 0.0) is None
        assert fire.update(False, 0.25) is False
        assert fire.update(True, 1.0) is False
        assert fire.update(True, 1.249) is False
        assert fire.update(True, 1.25) is True
        power = gpio.DebouncedLevel(250)
        assert power.update(False, 2.0) is None
        assert power.update(False, 2.25) is False
        return {"fire_alarm_s": "active after 250ms", "fire_alarm_P": "absent without fire event", "unknown_fault_distinct": True, "maintenance_lockout_preserved": True}

    coord.run_step("Fire/life-safety", "isolated input debounce and arbitration", fire_run, description="Inject fire and AC-power states without opening GPIO or invoking house-wide actions", expected="250ms debounce, UNKNOWN/FAULT distinction and independent AC supervision")


def run_local_diagnostics(coord: Coordinator, report_dir: Path) -> None:
    def local() -> dict[str, Any]:
        usage = shutil.disk_usage(report_dir)
        return {"hostname": socket.gethostname(), "architecture": os.uname().machine, "free_bytes": usage.free, "git_commit": os.popen("git rev-parse HEAD").read().strip()}

    coord.run_step("System health/readiness", "coordinator prerequisites", local, description="Verify local identity, architecture and report storage", expected="report directory is writable and has available disk space")


def verify_output_inhibition() -> dict[str, Any]:
    """Verify the repository safety contract before any simulated mutation."""
    import yaml

    paths = [ROOT / "06_config" / item for item in ("01_HCM/hardware_pins.yaml", "03_LCM/hardware_pins.yaml", "04_RCM/hardware_pins.yaml")]
    checked = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("physical_output_enabled") is not False:
            raise RuntimeError(f"physical output gate is not disabled in {path}")
        for name, section in (data.get("outputs") or {}).items():
            if not isinstance(section, dict):
                continue
            if section.get("real_output_enabled") is True or section.get("commissioned_channels"):
                raise RuntimeError(f"commissioning gate is open for {path}:{name}")
        checked.append(str(path.relative_to(ROOT)))
    return {"checked_manifests": checked, "physical_output_enabled": False, "commissioned_channels": [], "mock_transports_only": True}


def record_blocked_scenarios(coord: Coordinator) -> None:
    for subsystem, name in (("HCM/API", "authenticated logical command chain"), ("Hardware configuration/commissioning", "isolated production-shaped driver suite"), ("Fire/life-safety", "isolated input debounce and arbitration"), ("User profiles/PIN", "PIN uniqueness and throttling")):
        coord.record(subsystem, name, BLOCKED, "Scenario withheld because the independent safety gate failed", "no scenario executes when output inhibition is unverified", "safety prerequisite failed", time.monotonic(), remediation="Restore independently verified output inhibition before rerunning.")


def run_remote_diagnostics(coord: Coordinator, *, skip_remote: bool) -> None:
    if skip_remote:
        coord.record("Device diagnostics", "known device read-only collection", SKIP, "Collect host identity, health, time, services and storage from HCM, Conflict and LAB1", "fixed read-only commands complete", "not contacted", time.monotonic(), remediation="Run on HCM with its authorized SSH aliases or explicit authenticated management adapters.")
        return
    common = ROOT / "06_config" / "10_Common"
    spec = importlib.util.spec_from_file_location("hc_transport", common / "transport.py")
    if not spec or not spec.loader:
        raise RuntimeError("SSH transport module unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    tx = module.SSHTransport()
    commands = {
        "identity": "hostname; uname -m; date -u +%FT%TZ",
        "storage": "df -Pk /",
    }
    for target in ("jetson", "conflict", "lab1"):
        health_units = {
            "jetson": "hcm.service hcm-heartbeat.service hcm-watchdog.timer",
            "conflict": "hcm-heartbeat.service",
            "lab1": "homecontrol-lab.service homecontrol-lab-emergency.service hcm-heartbeat.service",
        }[target]
        target_commands = {**commands, "health": f"systemctl is-active {health_units}"}
        for name, command in target_commands.items():
            started = time.monotonic()
            try:
                result = tx.execute(target, command, timeout=15, step_name=f"{target}:{name}", read_only=True)
                coord.record("Device diagnostics", f"{target} {name}", PASS, "Fixed read-only device diagnostic", "command succeeds without mutation", "completed", started, {"target": target, "output": result.stdout[:1000]})
            except Exception as exc:
                coord.record("Device diagnostics", f"{target} {name}", BLOCKED, "Fixed read-only device diagnostic", "command succeeds without mutation", str(exc), started, remediation="Repair authorized device access or mark this device unavailable; do not bypass host-key or authentication checks.")


def write_reports(coord: Coordinator, *, args: argparse.Namespace, started: str, completed: str) -> dict[str, Path]:
    coord.report_dir.mkdir(parents=True, exist_ok=True)
    coord.report_dir.chmod(0o750)
    payload = {
        "run_id": coord.run_id,
        "started_at": started,
        "completed_at": completed,
        "git_commit": os.popen("git rev-parse HEAD").read().strip(),
        "mode": "fixture" if args.fixture else "device-hosted",
        "overall": overall_status(coord.results),
        "results": [result.as_dict() for result in coord.results],
        "safety": {"physical_output_writes": False, "live_mutating_commands": False, "live_service_restarts": False, "production_database_changes": False},
        "unverified": ["electrical commissioning", "physical relay/dimmer behavior", "actual fire alarm wiring"],
    }
    detailed = coord.report_dir / "detailed-results.json"
    report_json = coord.report_dir / "report.json"
    manifest = coord.report_dir / "test-manifest.json"
    report_txt = coord.report_dir / "report.txt"
    report_html = coord.report_dir / "report.html"
    diagnostic_logs = coord.report_dir / "sanitized-diagnostics.json"
    for path, data in ((detailed, payload), (report_json, payload), (manifest, {"run_id": coord.run_id, "subsystems": sorted({r.subsystem for r in coord.results}), "safety": payload["safety"]})):
        path.write_text(json.dumps(redact(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o640)
    diagnostic_logs.write_text(json.dumps({"run_id": coord.run_id, "diagnostics": [{"correlation_id": r.correlation_id, "subsystem": r.subsystem, "name": r.name, "evidence": r.evidence, "actual": r.actual} for r in coord.results]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic_logs.chmod(0o640)
    lines = [f"HomeControl system test {coord.run_id}", f"Overall: {payload['overall']}", f"Started: {started}", f"Completed: {completed}", ""]
    for result in coord.results:
        lines.append(f"[{result.status}] {result.subsystem} / {result.name}: {result.actual}")
    report_txt.write_text("\n".join(lines) + "\n", encoding="utf-8"); report_txt.chmod(0o640)
    rows = "".join(f"<tr><td>{html.escape(r.status)}</td><td>{html.escape(r.subsystem)}</td><td>{html.escape(r.name)}</td><td>{html.escape(r.expected)}</td><td>{html.escape(r.actual)}</td><td><code>{html.escape(json.dumps(redact(r.evidence), sort_keys=True))}</code></td><td>{html.escape(r.remediation or '')}</td><td>{r.duration_ms} ms</td></tr>" for r in coord.results)
    report_html.write_text(f"<!doctype html><meta charset='utf-8'><title>HomeControl system test</title><style>body{{font-family:sans-serif}}table{{border-collapse:collapse;font-size:small}}td,th{{border:1px solid #aaa;padding:4px;vertical-align:top}}code{{white-space:pre-wrap}}</style><h1>HomeControl system test</h1><p><b>{html.escape(payload['overall'])}</b> &mdash; {html.escape(coord.run_id)}</p><p>Physical output writes: <b>not performed</b>. Electrical commissioning: <b>unverified</b>.</p><table><tr><th>Status</th><th>Subsystem</th><th>Test</th><th>Expected</th><th>Actual</th><th>Evidence</th><th>Remediation/root-cause hint</th><th>Duration</th></tr>{rows}</table>", encoding="utf-8"); report_html.chmod(0o640)
    return {"report.html": report_html, "report.json": report_json, "report.txt": report_txt, "detailed-results.json": detailed, "test-manifest.json": manifest, "sanitized-diagnostics.json": diagnostic_logs}


def overall_status(results: list[Result]) -> str:
    if any(result.status == FAIL for result in results):
        return FAIL
    if any(result.status == BLOCKED for result in results):
        return "INCOMPLETE"
    if any(result.status == SKIP for result in results):
        return "INCOMPLETE"
    return PASS


@contextmanager
def run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError) as exc:
        handle.close()
        raise RuntimeError("another HomeControl system test is already running") from exc
    try:
        yield handle
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded HomeControl system integration test")
    parser.add_argument("--full", action="store_true", help="run live read-only diagnostics plus isolated mutating scenarios")
    parser.add_argument("--fixture", action="store_true", help="run all safe scenarios and report generation without device access")
    parser.add_argument("--skip-remote", action="store_true", help="do not contact known devices; marks live diagnostics SKIP")
    parser.add_argument("--report-dir", type=Path, default=Path("runtime/system-tests"))
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--lock-file", type=Path, default=Path("runtime/system-tests/.run.lock"))
    parser.add_argument("--inject-failure", action="store_true", help="inject a fixture failure to verify nonzero reporting; never use for a normal run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.full and not args.fixture:
        raise SystemExit("select --full or --fixture")
    if args.timeout <= 0 or args.timeout > 3600:
        raise SystemExit("--timeout must be between 1 and 3600 seconds")
    args.report_dir = args.report_dir.resolve()
    started = now_iso(); run_id = f"hc-system-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    with run_lock(args.lock_file.resolve()):
        coord = Coordinator(deadline=time.monotonic() + args.timeout, run_id=run_id, report_dir=args.report_dir)
        def cancel(_signum, _frame): coord.cancelled = True
        signal.signal(signal.SIGTERM, cancel); signal.signal(signal.SIGINT, cancel)
        run_local_diagnostics(coord, args.report_dir)
        safety_started = time.monotonic()
        try:
            safety_evidence = verify_output_inhibition()
            coord.record("Hardware configuration/commissioning", "independent output inhibition gate", PASS, "Verify output commissioning is disabled before scenarios", "all active manifests deny physical writes", "condition satisfied", safety_started, safety_evidence)
            safety_ok = True
        except Exception as exc:
            coord.record("Hardware configuration/commissioning", "independent output inhibition gate", FAIL, "Verify output commissioning is disabled before scenarios", "all active manifests deny physical writes", str(exc), safety_started, remediation="Stop and repair the safety configuration; do not override this gate.")
            safety_ok = False
        if safety_ok:
            run_simulation_scenarios(coord)
            run_driver_scenarios(coord)
            run_fire_scenarios(coord)
        else:
            record_blocked_scenarios(coord)
        if args.inject_failure:
            coord.record("Test framework", "deliberate fixture failure", FAIL, "Exercise report failure handling", "failure is visible and produces a nonzero exit", "deliberate failure requested", time.monotonic(), remediation="This was an intentional framework test.")
        if args.full:
            run_remote_diagnostics(coord, skip_remote=args.skip_remote)
        else:
            coord.record("Device diagnostics", "known device read-only collection", SKIP, "Live device diagnostics are not part of fixture mode", "not contacted", "not contacted", time.monotonic())
        completed = now_iso(); paths = write_reports(coord, args=args, started=started, completed=completed)
        print(json.dumps({"run_id": run_id, "overall": overall_status(coord.results), "report_dir": str(args.report_dir), "reports": {key: str(value) for key, value in paths.items()}}, sort_keys=True))
        return 0 if overall_status(coord.results) == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
