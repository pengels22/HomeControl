from __future__ import annotations

import hashlib
import hmac
import csv
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
LCM_CSV_HEADER = ["Channel ID", "Name", "Type", "Lockout", "eLight", "Max Brightness", "Fade Seconds", "Hardware ID"]

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

SWITCH_DEBOUNCE_MS = 250
BANK_TIMEOUT_MS = 5000


class OverrideState:
    WAIT_FOR_HIGH = "WAIT_FOR_HIGH"
    ARMED = "ARMED"
    WAIT_FOR_RELEASE = "WAIT_FOR_RELEASE"


class RCMBankController:
    """Debounced, mutually-exclusive RCM bank and front-panel override logic.

    Inputs passed to ``sample`` are asserted masks (bit 1 means the physical
    active-low contact is closed). ``update_from_raw`` converts MCP GPIO input
    bytes into those masks. Relay state is never changed by bank selection or
    timeout; only a qualified override calls the supplied dispatcher.
    """

    def __init__(self, dispatch, *, debounce_ms: int = SWITCH_DEBOUNCE_MS, timeout_ms: int = BANK_TIMEOUT_MS):
        self.dispatch = dispatch
        self.debounce_ms = int(debounce_ms)
        self.timeout_ms = int(timeout_ms)
        self.active_bank = 0
        self.last_bank_activity_ms = 0
        self.selection_generation = 0
        self.selector_conflict = False
        self._selector_raw = [False] * 4
        self._selector_stable = [False] * 4
        self._selector_changed_at = [0] * 4
        self._selector_initialized = False
        self._startup_release_required = False
        self._override_on_raw = [False] * 8
        self._override_off_raw = [False] * 8
        self._override_on_stable = [False] * 8
        self._override_off_stable = [False] * 8
        self._override_on_changed_at = [0] * 8
        self._override_off_changed_at = [0] * 8
        self._override_initialized = False
        self._high_since = [None] * 8
        self.override_states = [OverrideState.WAIT_FOR_HIGH] * 8

    @staticmethod
    def _elapsed(now: int, then: int) -> int:
        return (int(now) - int(then)) & 0xFFFFFFFF

    @staticmethod
    def _active_bank_from_stable(stable: list[bool]) -> int | None:
        selected = [index + 1 for index, value in enumerate(stable) if value]
        return selected[0] if len(selected) == 1 else None

    def _update_debounce(self, raw: list[bool], stable: list[bool], changed_at: list[int], now: int) -> bool:
        changed = False
        for index, value in enumerate(raw):
            if value != stable[index] and self._elapsed(now, changed_at[index]) >= self.debounce_ms:
                stable[index] = value
                changed = True
        return changed

    def _start_selection_interlock(self) -> None:
        self.selection_generation += 1
        self.override_states = [OverrideState.WAIT_FOR_HIGH] * 8
        self._high_since = [None] * 8

    def _update_raw(self, raw: list[bool], previous: list[bool], changed_at: list[int], now: int) -> None:
        for index, value in enumerate(raw):
            if value != previous[index]:
                previous[index] = value
                changed_at[index] = int(now) & 0xFFFFFFFF

    def _qualify_startup(self, now: int) -> None:
        if not self._startup_release_required:
            return
        if any(self._selector_stable) or any(self._override_on_stable) or any(self._override_off_stable):
            return
        if all(self._elapsed(now, value) >= self.debounce_ms for value in self._selector_changed_at):
            self._startup_release_required = False

    def _process_selection(self, now: int, rising_edge: bool) -> bool:
        if self._startup_release_required:
            return False
        selected_count = sum(self._selector_stable)
        if selected_count > 1:
            if self.active_bank or not self.selector_conflict:
                self.active_bank = 0
                self._start_selection_interlock()
            self.selector_conflict = True
            return True
        if selected_count == 0:
            self.selector_conflict = False
            return False
        if self.selector_conflict:
            return False
        bank = self._active_bank_from_stable(self._selector_stable)
        if bank is None:
            return False
        # A selector's stable inactive->asserted edge is the only selection event.
        if not rising_edge:
            return False
        self.active_bank = bank
        self.last_bank_activity_ms = int(now) & 0xFFFFFFFF
        self._start_selection_interlock()
        return True

    def _process_overrides(self, now: int) -> list[dict[str, Any]]:
        if not self.active_bank or self.selector_conflict or self._startup_release_required:
            return []
        operations = []
        for index in range(8):
            on = self._override_on_stable[index]
            off = self._override_off_stable[index]
            high = not on and not off
            if self.override_states[index] == OverrideState.WAIT_FOR_HIGH:
                if high:
                    if self._high_since[index] is None:
                        self._high_since[index] = int(now) & 0xFFFFFFFF
                    elif self._elapsed(now, self._high_since[index]) >= self.debounce_ms:
                        self.override_states[index] = OverrideState.ARMED
                else:
                    self._high_since[index] = None
                continue
            if self.override_states[index] == OverrideState.WAIT_FOR_RELEASE:
                if high:
                    if self._high_since[index] is None:
                        self._high_since[index] = int(now) & 0xFFFFFFFF
                    elif self._elapsed(now, self._high_since[index]) >= self.debounce_ms:
                        self.override_states[index] = OverrideState.ARMED
                else:
                    self._high_since[index] = None
                continue
            if on and off:
                self.override_states[index] = OverrideState.WAIT_FOR_RELEASE
                self._high_since[index] = None
                continue
            if not on and not off:
                continue
            value = on
            channel = (self.active_bank - 1) * 8 + index
            self.dispatch(channel, value)
            self.last_bank_activity_ms = int(now) & 0xFFFFFFFF
            self.override_states[index] = OverrideState.WAIT_FOR_RELEASE
            self._high_since[index] = None
            operations.append({"override": index + 1, "channel_index": channel, "value": value, "bank": self.active_bank, "generation": self.selection_generation})
        return operations

    def invalidate_inputs(self) -> None:
        """Discard a bank selection and require a fresh all-released sample sequence."""
        self.active_bank = 0
        self.selector_conflict = False
        self._start_selection_interlock()
        self._selector_initialized = False
        self._override_initialized = False
        self._startup_release_required = True

    def inputs_requalified(self, now_ms: int) -> bool:
        return (
            not self._startup_release_required
            and not any(self._selector_raw)
            and not any(self._override_on_raw)
            and not any(self._override_off_raw)
            and all(self._elapsed(now_ms, changed) >= self.debounce_ms for changed in self._selector_changed_at)
        )

    def sample(self, selector_asserted: int, override_on_asserted: int, override_off_asserted: int, now_ms: int) -> dict[str, Any]:
        now = int(now_ms) & 0xFFFFFFFF
        selectors = [bool(selector_asserted & (1 << index)) for index in range(4)]
        on = [bool(override_on_asserted & (1 << index)) for index in range(8)]
        off = [bool(override_off_asserted & (1 << index)) for index in range(8)]
        if not self._selector_initialized:
            self._selector_raw = selectors[:]
            self._selector_stable = [False] * 4
            self._selector_changed_at = [now] * 4
            self._selector_initialized = True
            self._startup_release_required = any(selectors)
        if not self._override_initialized:
            self._override_on_raw = on[:]
            self._override_off_raw = off[:]
            self._override_on_stable = [False] * 8
            self._override_off_stable = [False] * 8
            self._override_on_changed_at = [now] * 8
            self._override_off_changed_at = [now] * 8
            self._override_initialized = True
        self._update_raw(selectors, self._selector_raw, self._selector_changed_at, now)
        self._update_raw(on, self._override_on_raw, self._override_on_changed_at, now)
        self._update_raw(off, self._override_off_raw, self._override_off_changed_at, now)
        previous_selector_stable = self._selector_stable[:]
        selector_changed = self._update_debounce(self._selector_raw, self._selector_stable, self._selector_changed_at, now)
        selector_rising = any(not previous_selector_stable[index] and self._selector_stable[index] for index in range(4))
        self._update_debounce(self._override_on_raw, self._override_on_stable, self._override_on_changed_at, now)
        self._update_debounce(self._override_off_raw, self._override_off_stable, self._override_off_changed_at, now)
        self._qualify_startup(now)
        bank_changed = self._process_selection(now, selector_rising) if selector_changed or self.selector_conflict else False
        if self.active_bank and self._elapsed(now, self.last_bank_activity_ms) >= self.timeout_ms:
            self.active_bank = 0
            self.selector_conflict = False
            self._start_selection_interlock()
            bank_changed = True
        operations = [] if bank_changed else self._process_overrides(now)
        return self.status(now, operations=operations)

    def update_from_raw(self, mcp2_gpa: int, mcp1_gpa: int, mcp1_gpb: int, now_ms: int) -> dict[str, Any]:
        # All contacts are active LOW with pull-ups, so a zero GPIO bit is an
        # asserted logical input for the state machine.
        return self.sample((~int(mcp2_gpa)) & 0x0F, (~int(mcp1_gpa)) & 0xFF, (~int(mcp1_gpb)) & 0xFF, now_ms)

    def status(self, now_ms: int, *, operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        remaining = 0
        if self.active_bank:
            elapsed = self._elapsed(now_ms, self.last_bank_activity_ms)
            remaining = max(0, self.timeout_ms - elapsed)
        return {
            "active_bank": self.active_bank,
            "last_bank_activity_ms": self.last_bank_activity_ms,
            "timeout_ms": self.timeout_ms,
            "timeout_remaining_ms": remaining,
            "selector_conflict": self.selector_conflict,
            "selection_generation": self.selection_generation,
            "override_states": list(self.override_states),
            "operations": list(operations or []),
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


def lcm_channel_type(channel: str) -> str:
    if channel in LCM_RELAY_CHANNELS:
        return "Relay"
    if channel in LCM_ANALOG_DIMMER_CHANNELS:
        return "0-10V"
    if channel in LCM_HV_DIMMER_CHANNELS:
        return "110V"
    raise ValueError(f"invalid LCM channel {channel}")


def lcm_hardware_id(channel: str) -> str:
    return channel


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

    def provision_snapshot(self, snapshot: dict[str, Any], *, device_id: str) -> None:
        """Atomically install an HCM-authenticated, identity-bound user snapshot."""
        target = str(snapshot.get("target_device_id") or "").lower()
        if target != str(device_id).lower():
            raise ValueError("user snapshot device identity mismatch")
        users = snapshot.get("users")
        revision = snapshot.get("revision")
        checksum = snapshot.get("checksum")
        body = {"target_device_id": target, "revision": revision, "issued_at": snapshot.get("issued_at"), "users": users}
        if not isinstance(revision, str) or not isinstance(users, list) or checksum != stable_revision(body):
            raise ValueError("user snapshot integrity validation failed")
        current = self._read_snapshot()
        current_revision = current.get("revision")
        try:
            issued_at = int(snapshot.get("issued_at"))
        except (TypeError, ValueError):
            raise ValueError("invalid user snapshot issue time") from None
        if current.get("issued_at") is not None and issued_at < int(current["issued_at"]):
            raise ValueError("stale user snapshot revision")
        recovery_users = current.get("recovery_users") if isinstance(current.get("recovery_users"), list) else current.get("users", [])
        central_names = {str(item.get("username")) for item in users if isinstance(item, dict)}
        normalized_recovery = []
        for item in recovery_users:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if item.get("username") in central_names:
                item["username"] = f"recovery:{item['username']}"
            normalized_recovery.append(item)
        safe_users = []
        for user in users:
            if not isinstance(user, dict) or not all(user.get(key) for key in ("username", "verifier")):
                raise ValueError("malformed user snapshot")
            role = str(user.get("role", "")).upper()
            if role not in {"ADMIN", "READONLY"}:
                raise ValueError("unsupported user role")
            try:
                scheme, iterations, salt, digest = str(user["verifier"]).split("$", 3)
                if scheme != "pbkdf2_sha256" or int(iterations) < 100000:
                    raise ValueError
                bytes.fromhex(salt)
                bytes.fromhex(digest)
            except (TypeError, ValueError):
                raise ValueError("unsupported password verifier format") from None
            safe_users.append({
                "username": str(user["username"]),
                "role": role,
                "enabled": bool(user.get("enabled", True)),
                "verifier": str(user["verifier"]),
            })
        atomic_write_text(self.path, json.dumps({**body, "users": safe_users, "recovery_users": normalized_recovery, "updated_at": utc_ts()}, indent=2, sort_keys=True), mode=0o600)

    def has_users(self) -> bool:
        return bool(self._users())

    def _read_snapshot(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _users(self) -> dict[str, dict[str, Any]]:
        data = self._read_snapshot()
        users = list(data.get("recovery_users", [])) + list(data.get("users", []))
        return {item["username"]: item for item in users if isinstance(item, dict) and item.get("username")}

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
        if user.get("enabled", True) is not True:
            self._record_failure(username, now)
            return None
        verifier = user.get("verifier")
        if verifier:
            try:
                scheme, iterations_raw, salt, expected = str(verifier).split("$", 3)
                if scheme != "pbkdf2_sha256":
                    raise ValueError
                digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations_raw))
                valid = hmac.compare_digest(digest.hex(), expected)
            except (TypeError, ValueError):
                valid = False
        else:
            expected = bytes.fromhex(user["password_hash"])
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(user["salt"]), int(user.get("iterations", 310000)))
            valid = hmac.compare_digest(expected, digest)
        if not valid:
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

    def load_rcm_csv(self) -> list[dict[str, Any]]:
        path = self.path(".csv")
        if not path.exists():
            return default_rcm_config()
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows and list(rows[0].keys()) != ["Channel ID", "Name", "on", "Lockout"]:
            raise ValueError("invalid RCM CSV header")
        if len(rows) != 32:
            raise ValueError("RCM CSV must contain exactly 32 channels")
        channels = []
        for expected, row in zip(RCM_RELAY_CHANNELS, rows):
            if row.get("Channel ID") != expected:
                raise ValueError(f"expected RCM channel {expected}")
            channels.append({
                "channel": expected,
                "name": row.get("Name", ""),
                "on": row.get("on", "").strip().lower() in {"true", "1", "yes", "on"},
                "lockout": row.get("Lockout", "").strip().lower() in {"true", "1", "yes", "on"},
            })
        return channels

    def save_lcm_csv(self, channels: list[dict[str, Any]]) -> dict[str, Any]:
        expected_channels = [*LCM_RELAY_CHANNELS, *LCM_ANALOG_DIMMER_CHANNELS, *LCM_HV_DIMMER_CHANNELS]
        if len(channels) != 22:
            raise ValueError("LCM CSV must contain exactly 22 channels")
        path = self.path(".csv")
        rows = [LCM_CSV_HEADER]
        for expected, item in zip(expected_channels, channels):
            if item.get("channel") != expected:
                raise ValueError(f"expected LCM channel {expected}")
            expected_type = lcm_channel_type(expected)
            if str(item.get("type") or expected_type) != expected_type:
                raise ValueError(f"invalid type for LCM channel {expected}")
            is_dimmer = expected not in LCM_RELAY_CHANNELS
            rows.append([
                expected,
                str(item.get("name", "")),
                expected_type,
                "true" if item.get("lockout") else "false",
                "true" if item.get("emergency_lighting") else "false",
                "" if not is_dimmer else str(int(item.get("max_intensity", 100))),
                "" if not is_dimmer else str(float(item.get("fade_seconds", 3.0))),
                str(item.get("hardware_id") or lcm_hardware_id(expected)),
            ])
        text = "\n".join(",".join(csv_quote(cell) for cell in row) for row in rows) + "\n"
        atomic_write_text(path, text)
        return {"path": str(path), "revision": stable_revision(rows), "channel_count": 22}

    def load_lcm_csv(self) -> list[dict[str, Any]]:
        path = self.path(".csv")
        if not path.exists():
            return default_lcm_channels()
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows and list(rows[0].keys()) != LCM_CSV_HEADER:
            raise ValueError("invalid LCM CSV header")
        if len(rows) != 22:
            raise ValueError("LCM CSV must contain exactly 22 channels")
        expected_channels = [*LCM_RELAY_CHANNELS, *LCM_ANALOG_DIMMER_CHANNELS, *LCM_HV_DIMMER_CHANNELS]
        channels = []
        for expected, row in zip(expected_channels, rows):
            if row.get("Channel ID") != expected:
                raise ValueError(f"expected LCM channel {expected}")
            if row.get("Type") != lcm_channel_type(expected):
                raise ValueError(f"invalid type for LCM channel {expected}")
            is_dimmer = expected not in LCM_RELAY_CHANNELS
            channels.append({
                "channel": expected,
                "name": row.get("Name", ""),
                "type": row.get("Type"),
                "lockout": row.get("Lockout", "").strip().lower() in {"true", "1", "yes", "on"},
                "emergency_lighting": row.get("eLight", "").strip().lower() in {"true", "1", "yes", "on"},
                "max_intensity": int(float(row["Max Brightness"])) if is_dimmer and row.get("Max Brightness") else None,
                "fade_seconds": float(row["Fade Seconds"]) if is_dimmer and row.get("Fade Seconds") else None,
                "hardware_id": row.get("Hardware ID") or lcm_hardware_id(expected),
            })
        return channels


def csv_quote(value: Any) -> str:
    text = str(value)
    if any(ch in text for ch in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def default_rcm_config() -> list[dict[str, Any]]:
    return [{"channel": channel, "name": "", "on": False, "lockout": False} for channel in RCM_RELAY_CHANNELS]


def default_lcm_channels() -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    for channel in [*LCM_RELAY_CHANNELS, *LCM_ANALOG_DIMMER_CHANNELS, *LCM_HV_DIMMER_CHANNELS]:
        is_dimmer = channel not in LCM_RELAY_CHANNELS
        channels.append({
            "channel": channel,
            "name": "",
            "type": lcm_channel_type(channel),
            "lockout": False,
            "emergency_lighting": False,
            "max_intensity": 100 if is_dimmer else None,
            "fade_seconds": 3.0 if is_dimmer else None,
            "hardware_id": lcm_hardware_id(channel),
        })
    return channels


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
