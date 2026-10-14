from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


I2C_COMPONENTS = {
    "relay_card_1": {"name": "Relay Card 1", "address": 0x20},
    "relay_card_2": {"name": "Relay Card 2", "address": 0x21},
    "mcp1": {"name": "MCP1", "address": 0x26},
    "mcp2": {"name": "MCP2", "address": 0x27},
}

RCM_RELAY_CHANNELS = [f"{bank}{channel}" for bank in ("A", "B", "C", "D") for channel in range(1, 9)]
LCM_RELAY_CHANNELS = [f"A{channel}" for channel in range(1, 9)]
LCM_ANALOG_DIMMER_CHANNELS = [f"10-{channel}" for channel in range(1, 11)]
LCM_HV_DIMMER_CHANNELS = [f"HV-{channel}" for channel in range(1, 5)]

RCM_RELAY_MAP = {
    **{f"A{i + 1}": ("relay_card_1", i) for i in range(8)},
    **{f"B{i + 1}": ("relay_card_1", i + 8) for i in range(8)},
    **{f"C{i + 1}": ("relay_card_2", i) for i in range(8)},
    **{f"D{i + 1}": ("relay_card_2", i + 8) for i in range(8)},
}

MCP1_SWITCH_ASSIGNMENTS = {
    **{f"override_on_{i + 1}": {"port": "A", "pin": i, "position": i + 1} for i in range(8)},
    **{f"override_off_{i + 1}": {"port": "B", "pin": i, "position": i + 1} for i in range(8)},
}

MCP2_ASSIGNMENTS = {
    "bank_1": {"port": "A", "pin": 0},
    "bank_2": {"port": "A", "pin": 1},
    "bank_3": {"port": "A", "pin": 2},
    "bank_4": {"port": "A", "pin": 3},
    "power_led": {"port": "A", "pin": 4},
    "link_led": {"port": "A", "pin": 5},
    "status_led": {"port": "A", "pin": 6},
    "fault_led": {"port": "A", "pin": 7},
}


def utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_revision(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def config_checksum(value: Any) -> str:
    return stable_revision(value)


def build_config_package(module_type: str, logical_id: str, config: dict[str, Any], *, revision: str | None = None) -> dict[str, Any]:
    body = {
        "module_type": module_type.upper(),
        "logical_id": logical_id,
        "config": config,
    }
    revision = revision or stable_revision(body)
    body.update({
        "revision": revision,
        "checksum": config_checksum({"revision": revision, "config": config}),
        "generated_at": utc_ts(),
    })
    return body


def verify_config_package(payload: dict[str, Any], *, module_type: str, logical_id: str | None = None) -> None:
    if str(payload.get("module_type", "")).upper() != module_type.upper():
        raise ValueError("configuration module type mismatch")
    if logical_id and payload.get("logical_id") not in {logical_id, None}:
        raise ValueError("configuration logical identity mismatch")
    revision = payload.get("revision")
    checksum = payload.get("checksum")
    if not revision or not isinstance(revision, str):
        raise ValueError("configuration revision is required")
    if checksum != config_checksum({"revision": revision, "config": payload.get("config", {})}):
        raise ValueError("configuration checksum mismatch")


def reconcile_lockouts(authoritative: dict[str, Any], local: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    merged = json.loads(json.dumps(authoritative))
    conflicts: list[dict[str, Any]] = []
    local_lockouts = _lockout_map(local)
    if not local_lockouts:
        return merged, conflicts
    for section in ("channels", "relays", "analog_dimmers", "hv_dimmers"):
        items = merged.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            channel = item.get("channel")
            if channel in local_lockouts and local_lockouts[channel] and not item.get("lockout"):
                item["lockout"] = True
                conflicts.append({"channel": channel, "resolution": "preserved_local_lockout"})
    return merged, conflicts


def _lockout_map(config: dict[str, Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for section in ("channels", "relays", "analog_dimmers", "hv_dimmers"):
        for item in config.get(section) or []:
            if isinstance(item, dict) and item.get("channel"):
                result[str(item["channel"])] = bool(item.get("lockout"))
    return result


def atomic_write_text(path: Path, text: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


@dataclass
class ComponentHealth:
    name: str
    category: str
    ok: bool = True
    status: str = "online"
    address: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "ok": self.ok,
            "status": self.status,
            "address": self.address,
            "detail": self.detail,
            "metadata": self.metadata,
        }


class PeripheralRegistry:
    def __init__(self) -> None:
        self.components: dict[str, ComponentHealth] = {}

    def register(self, key: str, *, name: str, category: str, address: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        self.components[key] = ComponentHealth(name=name, category=category, address=address, metadata=metadata or {})

    def set_fault(self, key: str, detail: str, status: str = "offline") -> ComponentHealth:
        component = self.components[key]
        component.ok = False
        component.status = status
        component.detail = detail
        return component

    def clear_fault(self, key: str) -> ComponentHealth:
        component = self.components[key]
        component.ok = True
        component.status = "online"
        component.detail = None
        return component

    def grouped(self) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {"i2c": [], "can": [], "network_io": []}
        for component in self.components.values():
            groups.setdefault(component.category, []).append(component.as_dict())
        return groups

    def active_faults(self) -> list[dict[str, Any]]:
        return [component.as_dict() for component in self.components.values() if not component.ok]


@dataclass
class EventRecord:
    event_id: str
    timestamp: str
    module_id: str
    component: str
    hardware_id: str | None
    category: str
    severity: str
    code: str
    message: str
    incident_id: str
    metadata: dict[str, Any]
    delivered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class StructuredEventLogger:
    def __init__(self, module_id: str, log_dir: Path, *, max_bytes: int = 512_000) -> None:
        self.module_id = module_id
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self._incidents: dict[tuple[str, str], dict[str, Any]] = {}

    @property
    def current_log(self) -> Path:
        return self.log_dir / "events.jsonl"

    def _rotate_if_needed(self) -> None:
        path = self.current_log
        if path.exists() and path.stat().st_size >= self.max_bytes:
            rotated = self.log_dir / f"events-{int(time.time())}.jsonl"
            os.replace(path, rotated)

    def log(
        self,
        *,
        component: str,
        category: str,
        severity: str,
        code: str,
        message: str,
        hardware_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        safety_significant: bool = False,
    ) -> dict[str, Any] | None:
        key = (component, code)
        incident = self._incidents.get(key)
        if severity.lower() in {"recovered", "recovery", "info"} and incident:
            incident_id = incident["incident_id"]
            self._incidents.pop(key, None)
        else:
            if not incident:
                incident = {"incident_id": str(uuid.uuid4()), "count": 0}
                self._incidents[key] = incident
            incident["count"] += 1
            if incident["count"] > 3 and not safety_significant:
                return None
            incident_id = incident["incident_id"]
            if incident["count"] == 3 and not safety_significant:
                message = f"{message}; additional duplicate messages suppressed"
        record = EventRecord(
            event_id=str(uuid.uuid4()),
            timestamp=utc_ts(),
            module_id=self.module_id,
            component=component,
            hardware_id=hardware_id,
            category=category,
            severity=severity,
            code=code,
            message=message,
            incident_id=incident_id,
            metadata=metadata or {},
        )
        self._rotate_if_needed()
        self.current_log.parent.mkdir(parents=True, exist_ok=True)
        with self.current_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")
        return record.as_dict()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        path = self.current_log
        if not path.exists():
            return []
        lines = path.read_text().splitlines()[-max(0, int(limit)):]
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result


class OfflineEventQueue:
    def __init__(self, path: Path, *, max_records: int = 5000) -> None:
        self.path = Path(path)
        self.max_records = max_records

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        atomic_write_text(self.path, json.dumps(records[-self.max_records:], indent=2, sort_keys=True))

    def enqueue(self, record: dict[str, Any]) -> None:
        records = self._read()
        ids = {item.get("event_id") for item in records}
        if record.get("event_id") not in ids:
            records.append(record)
        self._write(records)

    def batch(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._read()[:limit]

    def mark_delivered(self, event_ids: Iterable[str]) -> None:
        delivered = set(event_ids)
        self._write([item for item in self._read() if item.get("event_id") not in delivered])

    def count(self) -> int:
        return len(self._read())


class LocalAuthStore:
    def __init__(self, path: Path, *, session_ttl_s: int = 1800, max_failures: int = 5, lockout_s: int = 300) -> None:
        self.path = Path(path)
        self.session_ttl_s = session_ttl_s
        self.max_failures = max_failures
        self.lockout_s = lockout_s
        self.sessions: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, dict[str, Any]] = {}

    def provision_hashes(self, users: list[dict[str, Any]]) -> None:
        safe_users = []
        for user in users:
            if not all(user.get(key) for key in ("username", "salt", "password_hash")):
                continue
            safe_users.append({
                "username": str(user["username"]),
                "role": str(user.get("role", "ADMIN")).upper(),
                "salt": str(user["salt"]),
                "password_hash": str(user["password_hash"]),
                "iterations": int(user.get("iterations", 310000)),
                "expires_at": user.get("expires_at"),
            })
        atomic_write_text(self.path, json.dumps({"users": safe_users, "updated_at": utc_ts()}, indent=2, sort_keys=True), mode=0o600)

    def has_users(self) -> bool:
        return bool(self._users())

    def _users(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}
        return {item["username"]: item for item in data.get("users", []) if isinstance(item, dict) and item.get("username")}

    @staticmethod
    def hash_password(password: str, salt_hex: str | None = None, iterations: int = 310000) -> dict[str, Any]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return {"salt": salt.hex(), "password_hash": digest.hex(), "iterations": iterations}

    def authenticate(self, username: str, password: str, *, now: float | None = None) -> dict[str, Any] | None:
        now = time.time() if now is None else now
        failure = self.failures.get(username, {"count": 0, "locked_until": 0.0})
        if failure.get("locked_until", 0.0) > now:
            return None
        user = self._users().get(username)
        if not user:
            self._record_failure(username, now)
            return None
        expected = bytes.fromhex(user["password_hash"])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(user["salt"]), int(user.get("iterations", 310000)))
        if not hmac.compare_digest(expected, digest):
            self._record_failure(username, now)
            return None
        self.failures.pop(username, None)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        session = {"token": token, "csrf": csrf, "username": username, "role": user.get("role", "ADMIN"), "expires_at": now + self.session_ttl_s}
        self.sessions[token] = session
        return session

    def _record_failure(self, username: str, now: float) -> None:
        failure = self.failures.setdefault(username, {"count": 0, "locked_until": 0.0})
        failure["count"] += 1
        if failure["count"] >= self.max_failures:
            failure["locked_until"] = now + self.lockout_s
            failure["count"] = 0

    def session(self, token: str | None, *, now: float | None = None) -> dict[str, Any] | None:
        if not token:
            return None
        now = time.time() if now is None else now
        session = self.sessions.get(token)
        if not session:
            return None
        if session["expires_at"] <= now:
            self.sessions.pop(token, None)
            return None
        return session

    def require_csrf(self, token: str | None, csrf: str | None) -> bool:
        session = self.session(token)
        return bool(session and csrf and hmac.compare_digest(str(session["csrf"]), str(csrf)))


class LocalConfigStore:
    def __init__(self, root: Path, module_type: str, logical_id: str) -> None:
        self.root = Path(root)
        self.module_type = module_type.upper()
        self.logical_id = logical_id

    @property
    def module_dir(self) -> Path:
        return self.root / "config" / self.module_type

    def path(self, suffix: str) -> Path:
        return self.module_dir / f"{self.logical_id}{suffix}"

    def save_json(self, value: dict[str, Any]) -> dict[str, Any]:
        body = {**value, "revision": stable_revision(value), "updated_at": utc_ts()}
        atomic_write_text(self.path(".json"), json.dumps(body, indent=2, sort_keys=True))
        return body

    def load_json(self) -> dict[str, Any]:
        path = self.path(".json")
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}

    def save_rcm_csv(self, channels: list[dict[str, Any]]) -> dict[str, Any]:
        if len(channels) != 32:
            raise ValueError("RCM CSV must contain exactly 32 channels")
        path = self.path(".csv")
        rows = [["Channel ID", "Name", "on", "Lockout"]]
        for expected, item in zip(RCM_RELAY_CHANNELS, channels):
            if item.get("channel") != expected:
                raise ValueError(f"expected RCM channel {expected}")
            rows.append([
                expected,
                str(item.get("name", "")),
                "true" if item.get("on") else "false",
                "true" if item.get("lockout") else "false",
            ])
        text = "\n".join(",".join(csv_quote(cell) for cell in row) for row in rows) + "\n"
        atomic_write_text(path, text)
        return {"path": str(path), "revision": stable_revision(rows), "channel_count": 32}


def csv_quote(value: Any) -> str:
    text = str(value)
    if any(ch in text for ch in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def default_rcm_config() -> list[dict[str, Any]]:
    return [{"channel": channel, "name": "", "on": False, "lockout": False} for channel in RCM_RELAY_CHANNELS]


def default_lcm_config() -> dict[str, Any]:
    return {
        "relays": [{"channel": channel, "name": "", "emergency_lighting": False, "lockout": False} for channel in LCM_RELAY_CHANNELS],
        "analog_dimmers": [
            {"channel": channel, "name": "", "emergency_lighting": False, "lockout": False, "max_intensity": 100, "fade_seconds": 3.0}
            for channel in LCM_ANALOG_DIMMER_CHANNELS
        ],
        "hv_dimmers": [
            {"channel": channel, "name": "", "emergency_lighting": False, "lockout": False, "max_intensity": 100, "fade_seconds": 3.0}
            for channel in LCM_HV_DIMMER_CHANNELS
        ],
        "hardware": {
            "analog_pwm": {"real_output_enabled": False, "model": None, "address": None},
            "shelly": {"real_output_enabled": False, "modules": []},
        },
    }


def compute_led_state(*, initialized: bool, heartbeat_ack_current: bool, active_faults: Iterable[Any], internet_ok: bool | None = None, is_hcm: bool = False) -> dict[str, bool]:
    has_fault = bool(list(active_faults))
    if is_hcm and internet_ok is False:
        has_fault = True
    status_ok = not has_fault
    if is_hcm and internet_ok is False:
        status_ok = False
    return {
        "POWER": bool(initialized),
        "LINK": bool(heartbeat_ack_current),
        "STATUS": status_ok,
        "FAULT": has_fault,
    }


def selected_bank_from_mcp2(gpa_bits: int) -> int:
    selected = [index + 1 for index in range(4) if gpa_bits & (1 << index)]
    if len(selected) != 1:
        raise ValueError("ambiguous or missing bank selection")
    return selected[0]


class DebouncedInput:
    def __init__(self, stable_after_s: float = 0.05) -> None:
        self.stable_after_s = stable_after_s
        self._candidate: Any = None
        self._candidate_since = 0.0
        self.value: Any = None

    def update(self, value: Any, now: float | None = None) -> Any:
        now = time.monotonic() if now is None else now
        if value != self._candidate:
            self._candidate = value
            self._candidate_since = now
            return self.value
        if now - self._candidate_since >= self.stable_after_s:
            self.value = value
        return self.value


def git_status_simple(repo: Path, remote_name: str | None = None) -> dict[str, Any]:
    repo = Path(repo)
    if not (repo / ".git").exists():
        return {"local_enabled": False, "remote_configured": False, "display": "Local Git not initialized"}
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True, check=False)
    dirty = bool(result.stdout.strip()) if result.returncode == 0 else True
    remote_configured = bool(remote_name)
    if dirty:
        display = "Git Repository: Not Synced"
    elif remote_configured:
        local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=False)
        remote = subprocess.run(["git", "rev-parse", f"{remote_name}/HEAD"], cwd=repo, text=True, capture_output=True, check=False)
        display = "Git Repository: Up to Date" if local.returncode == 0 and remote.returncode == 0 and local.stdout == remote.stdout else "Git Repository: Not Synced"
    else:
        display = "Local Git enabled (no GitHub remote)"
    return {"local_enabled": True, "remote_configured": remote_configured, "dirty": dirty, "display": display}
