from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from homecontrol_identity import InvalidDeviceId, maybe_normalize_device_id

from . import db
from .management import audit_event
from .settings import settings


ALLOWED_ROLES = ("UNASSIGNED", "RCM", "SIM", "LCM")
TERMINAL_STATUSES = {"CONFIRMED", "REJECTED", "TIMED_OUT", "FAILED"}
ACTIVE_STATUSES = {"PENDING", "SENT", "ACCEPTED", "APPLYING"}


class RoleSwitchError(ValueError):
    pass


class RoleSwitchNotFound(KeyError):
    pass


@asynccontextmanager
async def _transaction(conn):
    tx_factory = getattr(conn, "transaction", None)
    if tx_factory is None:
        yield
        return
    async with tx_factory():
        yield


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _wire_value(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _wire_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_wire_value(v) for v in value]
    return value


def normalize_role(role: str) -> str:
    normalized = str(role or "").strip().upper()
    if normalized not in ALLOWED_ROLES:
        raise RoleSwitchError(f"unsupported role {role}")
    return normalized


def normalize_device_id(device_id: str) -> str:
    try:
        return maybe_normalize_device_id(device_id)
    except InvalidDeviceId:
        raise RoleSwitchError("invalid device_id") from None


def role_switch_enabled(device_id: str) -> bool:
    return device_id == maybe_normalize_device_id(settings.lab1_device_id)


def _transition(row) -> dict[str, Any]:
    return {
        "operation_id": str(row["operation_id"]),
        "module_id": int(row["module_id"]),
        "device_id": row["device_id"],
        "actor": row["actor"],
        "previous_role": row["previous_role"],
        "requested_role": row["requested_role"],
        "status": row["status"],
        "simulation_required": bool(row["simulation_required"]),
        "control_session_key": row["control_session_key"],
        "error": row["error"],
        "rejection_reason": row["rejection_reason"],
        "command_payload": _wire_value(row["command_payload"] or {}),
        "ack_payload": _wire_value(row["ack_payload"] or {}),
        "requested_at": _wire_value(row["requested_at"]),
        "sent_at": _wire_value(row["sent_at"]),
        "accepted_at": _wire_value(row["accepted_at"]),
        "completed_at": _wire_value(row["completed_at"]),
        "expires_at": _wire_value(row["expires_at"]),
    }


def _role_summary(module: dict[str, Any], transition: dict[str, Any] | None) -> dict[str, Any]:
    state = _json_value(module.get("last_state") or {})
    nested = state.get("state") if isinstance(state.get("state"), dict) else state
    operational_role = None
    simulation = None
    physical_outputs_enabled = None
    if isinstance(nested, dict):
        operational_role = nested.get("lab_role") or nested.get("operational_role")
        simulation = nested.get("simulation")
        physical_outputs_enabled = nested.get("physical_outputs_enabled")
    return {
        "enabled": role_switch_enabled(module["device_id"]),
        "current_role": operational_role,
        "requested_role": transition["requested_role"] if transition and transition["status"] in ACTIVE_STATUSES else None,
        "last_transition": transition,
        "simulation": simulation,
        "physical_outputs_enabled": physical_outputs_enabled,
    }


async def list_role_managed_modules() -> list[dict[str, Any]]:
    await mark_timeouts()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM modules
            WHERE device_id=$1
            ORDER BY hostname
            """,
            maybe_normalize_device_id(settings.lab1_device_id),
        )
        transitions = await conn.fetch(
            """
            SELECT DISTINCT ON (device_id) *
            FROM module_role_transitions
            WHERE device_id=$1
            ORDER BY device_id, requested_at DESC
            """,
            maybe_normalize_device_id(settings.lab1_device_id),
        )
    by_device = {row["device_id"]: _transition(row) for row in transitions}
    result = []
    for row in rows:
        module = {
            "id": int(row["id"]),
            "device_id": row["device_id"],
            "hostname": row["hostname"],
            "module_type": row["module_type"],
            "ip_address": str(row["ip_address"]),
            "online": bool(row["online"]),
            "control_session_online": bool(row["control_session_online"]),
            "last_seen": _wire_value(row["last_seen"]),
            "last_state": _wire_value(row["last_state"] or {}),
        }
        module["role_management"] = _role_summary(module, by_device.get(row["device_id"]))
        result.append(module)
    return result


async def get_transition(operation_id: str) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM module_role_transitions WHERE operation_id=$1::uuid",
            operation_id,
        )
    if not row:
        raise RoleSwitchNotFound(operation_id)
    return _transition(row)


async def create_transition(
    *,
    device_id: str,
    requested_role: str,
    actor: str,
    control_session_key: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    device_id = normalize_device_id(device_id)
    requested_role = normalize_role(requested_role)
    if not role_switch_enabled(device_id):
        raise RoleSwitchError("device is not approved for role switching")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    operation_id = str(uuid.uuid4())
    async with db.acquire() as conn:
        async with _transaction(conn):
            module = await conn.fetchrow(
                """
                SELECT *
                FROM modules
                WHERE device_id=$1
                FOR UPDATE
                """,
                device_id,
            )
            if not module:
                raise RoleSwitchError("module is not registered")
            if not module["control_session_online"]:
                raise RoleSwitchError("module has no authenticated online control session")
            if control_session_key != device_id:
                raise RoleSwitchError("control session identity does not match requested device")
            await conn.execute(
                """
                UPDATE module_role_transitions
                SET status='TIMED_OUT',
                    completed_at=now(),
                    error='role transition timed out'
                WHERE device_id=$1
                  AND status=ANY($2::text[])
                  AND expires_at <= now()
                """,
                device_id,
                list(ACTIVE_STATUSES),
            )
            active = await conn.fetchrow(
                """
                SELECT operation_id
                FROM module_role_transitions
                WHERE device_id=$1
                  AND status=ANY($2::text[])
                  AND expires_at > now()
                LIMIT 1
                """,
                device_id,
                list(ACTIVE_STATUSES),
            )
            if active:
                raise RoleSwitchError("another role transition is already active")
            binding = await conn.fetchrow(
                """
                SELECT id
                FROM device_bindings
                WHERE module_id=$1
                  AND enabled=true
                LIMIT 1
                """,
                module["id"],
            )
            if binding:
                raise RoleSwitchError("active bindings must be reviewed before role switching")
            state = _json_value(module["last_state"] or {})
            nested = state.get("state") if isinstance(state, dict) else {}
            previous_role = nested.get("lab_role") if isinstance(nested, dict) else None
            previous_role = previous_role or "UNASSIGNED"
            command_payload = {
                "op": "set_module_role",
                "device_id": device_id,
                "requested_role": requested_role,
                "simulation_required": True,
            }
            row = await conn.fetchrow(
                """
                INSERT INTO module_role_transitions(
                    operation_id, module_id, device_id, actor, previous_role,
                    requested_role, status, simulation_required, control_session_key,
                    command_payload, expires_at
                )
                VALUES($1::uuid,$2,$3,$4,$5,$6,'PENDING',true,$7,$8::jsonb,$9)
                RETURNING *
                """,
                operation_id,
                module["id"],
                device_id,
                actor,
                previous_role,
                requested_role,
                control_session_key,
                _json_dumps(command_payload),
                expires_at,
            )
            after = _transition(row)
            await audit_event(
                conn,
                actor=actor,
                action="module_role.request",
                target_type="module",
                target_id=device_id,
                before_state={"role": previous_role},
                after_state=after,
            )
    return after


async def mark_sent(operation_id: str, actor: str = "hcm") -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            before = await conn.fetchrow(
                "SELECT * FROM module_role_transitions WHERE operation_id=$1::uuid FOR UPDATE",
                operation_id,
            )
            if not before:
                raise RoleSwitchNotFound(operation_id)
            row = await conn.fetchrow(
                """
                UPDATE module_role_transitions
                SET status='SENT', sent_at=now()
                WHERE operation_id=$1::uuid
                RETURNING *
                """,
                operation_id,
            )
            after = _transition(row)
            await audit_event(conn, actor=actor, action="module_role.sent", target_type="module_role_transition", target_id=operation_id, before_state=_transition(before), after_state=after)
    return after


async def mark_acknowledged(operation_id: str, ack_payload: dict[str, Any], actor: str = "hcm") -> dict[str, Any]:
    accepted = bool(ack_payload.get("ok") is True and ack_payload.get("accepted") is not False)
    status = "ACCEPTED" if accepted else "REJECTED"
    reason = None if accepted else str(ack_payload.get("error") or ack_payload.get("reason") or "module rejected role transition")
    async with db.acquire() as conn:
        async with _transaction(conn):
            before = await conn.fetchrow(
                "SELECT * FROM module_role_transitions WHERE operation_id=$1::uuid FOR UPDATE",
                operation_id,
            )
            if not before:
                raise RoleSwitchNotFound(operation_id)
            if before["status"] in TERMINAL_STATUSES:
                return _transition(before)
            row = await conn.fetchrow(
                """
                UPDATE module_role_transitions
                SET status=$2,
                    accepted_at=CASE WHEN $2='ACCEPTED' THEN now() ELSE accepted_at END,
                    completed_at=CASE WHEN $2='REJECTED' THEN now() ELSE completed_at END,
                    ack_payload=$3::jsonb,
                    rejection_reason=$4
                WHERE operation_id=$1::uuid
                RETURNING *
                """,
                operation_id,
                status,
                _json_dumps(ack_payload),
                reason,
            )
            after = _transition(row)
            await audit_event(conn, actor=actor, action=f"module_role.{status.lower()}", target_type="module_role_transition", target_id=operation_id, before_state=_transition(before), after_state=after)
    return after


async def mark_failed(operation_id: str, error: str, actor: str = "hcm") -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            before = await conn.fetchrow(
                "SELECT * FROM module_role_transitions WHERE operation_id=$1::uuid FOR UPDATE",
                operation_id,
            )
            if not before:
                raise RoleSwitchNotFound(operation_id)
            if before["status"] in TERMINAL_STATUSES:
                return _transition(before)
            row = await conn.fetchrow(
                """
                UPDATE module_role_transitions
                SET status='FAILED', completed_at=now(), error=$2
                WHERE operation_id=$1::uuid
                RETURNING *
                """,
                operation_id,
                error,
            )
            after = _transition(row)
            await audit_event(conn, actor=actor, action="module_role.failed", target_type="module_role_transition", target_id=operation_id, before_state=_transition(before), after_state=after)
    return after


async def mark_timeouts(actor: str = "hcm") -> int:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE module_role_transitions
            SET status='TIMED_OUT',
                completed_at=now(),
                error='role transition timed out'
            WHERE status=ANY($1::text[])
              AND expires_at <= now()
            RETURNING *
            """,
            list(ACTIVE_STATUSES),
        )
        for row in rows:
            await audit_event(
                conn,
                actor=actor,
                action="module_role.timed_out",
                target_type="module_role_transition",
                target_id=str(row["operation_id"]),
                before_state=None,
                after_state=_transition(row),
            )
    return len(rows)


async def confirm_from_state(device_id: str | None, state_payload: dict[str, Any]) -> dict[str, Any] | None:
    if not device_id or not isinstance(state_payload, dict):
        return None
    state = state_payload.get("state") if isinstance(state_payload.get("state"), dict) else state_payload
    if not isinstance(state, dict):
        return None
    role = state.get("lab_role") or state.get("operational_role")
    if not role:
        return None
    physical_outputs_enabled = bool(state.get("physical_outputs_enabled") is True)
    simulation = bool(state.get("simulation") is True)
    async with db.acquire() as conn:
        async with _transaction(conn):
            before = await conn.fetchrow(
                """
                SELECT *
                FROM module_role_transitions
                WHERE device_id=$1
                  AND status=ANY($2::text[])
                  AND requested_role=$3
                  AND expires_at > now()
                ORDER BY requested_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                device_id,
                ["ACCEPTED", "APPLYING"],
                role,
            )
            if not before:
                return None
            if physical_outputs_enabled or not simulation:
                row = await conn.fetchrow(
                    """
                    UPDATE module_role_transitions
                    SET status='FAILED',
                        completed_at=now(),
                        error='unsafe role state reported by module'
                    WHERE operation_id=$1
                    RETURNING *
                    """,
                    before["operation_id"],
                )
                after = _transition(row)
                await audit_event(conn, actor="hcm", action="module_role.failed", target_type="module_role_transition", target_id=str(row["operation_id"]), before_state=_transition(before), after_state=after)
                return after
            row = await conn.fetchrow(
                """
                UPDATE module_role_transitions
                SET status='CONFIRMED',
                    completed_at=now()
                WHERE operation_id=$1
                RETURNING *
                """,
                before["operation_id"],
            )
            after = _transition(row)
            await audit_event(conn, actor="hcm", action="module_role.confirmed", target_type="module_role_transition", target_id=str(row["operation_id"]), before_state=_transition(before), after_state=after)
            return after
