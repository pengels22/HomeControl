from __future__ import annotations

import json
import re
from datetime import date, datetime
from contextlib import asynccontextmanager
from typing import Any

from homecontrol_identity import InvalidDeviceId, maybe_normalize_device_id

from . import db


UNSET = object()


@asynccontextmanager
async def _transaction(conn):
    tx_factory = getattr(conn, "transaction", None)
    if tx_factory is None:
        yield
        return
    async with tx_factory():
        yield


class NotFoundError(KeyError):
    pass


class ValidationError(ValueError):
    pass


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
    if isinstance(value, dict):
        return {k: _wire_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_wire_value(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _module_selector(identifier: str | int) -> tuple[str, str | None]:
    text = str(identifier).strip()
    if not text:
        raise ValidationError("module identifier is required")
    try:
        device_id = maybe_normalize_device_id(text)
    except InvalidDeviceId:
        device_id = None
    return text, device_id


def _module_summary(row, capabilities: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "device_id": row["device_id"],
        "module_uuid": str(row["module_uuid"]) if row["module_uuid"] else None,
        "identity_interface": row["identity_interface"],
        "module_type": row["module_type"],
        "hostname": row["hostname"],
        "ip_address": str(row["ip_address"]),
        "heartbeat_ip": str(row["heartbeat_ip"]) if row["heartbeat_ip"] else None,
        "online": bool(row["online"]),
        "control_session_online": bool(row["control_session_online"]),
        "supervision_state": row["supervision_state"],
        "supervision_last_seen": _wire_value(row["supervision_last_seen"]),
        "supervision_fresh_until": _wire_value(row["supervision_fresh_until"]),
        "last_seen": _wire_value(row["last_seen"]),
        "software_version": row["software_version"],
        "hardware_revision": row["hardware_revision"],
        "config_version": int(row["config_version"]),
        "last_state": _wire_value(row["last_state"] or {}),
        "last_health": _wire_value(row["last_health"] or {}),
        "commissioned_at": _wire_value(row["commissioned_at"]),
        "capabilities": capabilities or [],
    }


def _logical_device(row) -> dict[str, Any]:
    try:
        room = row["room"]
    except (KeyError, IndexError):
        room = None
    return {
        "id": int(row["id"]),
        "logical_name": row["logical_name"],
        "room_id": int(row["room_id"]) if row["room_id"] is not None else None,
        "room": room,
        "device_class": row["device_class"],
        "enabled": bool(row["enabled"]),
        "maintenance_locked": bool(row["maintenance_locked"]),
        "metadata": _wire_value(row["metadata"] or {}),
    }


def _binding(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "logical_device_id": int(row["logical_device_id"]),
        "logical_name": row["logical_name"],
        "module_id": int(row["module_id"]),
        "module_hostname": row["hostname"],
        "module_device_id": row["device_id"],
        "module_type": row["module_type"],
        "channel": row["channel"],
        "binding_type": row["binding_type"],
        "enabled": bool(row["enabled"]),
        "metadata": _wire_value(row["metadata"] or {}),
    }


def _capability_names(rows) -> set[str]:
    return {str(row["capability"]) for row in rows}


def _normalize_channel(channel: str | None) -> str | None:
    if channel is None:
        return None
    clean = str(channel).strip()
    return clean.upper() if clean else None


def _module_supports_channel(module_type: str, channel: str | None, capabilities: set[str]) -> bool:
    if module_type == "PNL":
        return channel is None or "panel" in capabilities or "kiosk" in capabilities
    if channel is None:
        return False
    if module_type == "RCM":
        return bool(re.fullmatch(r"[ABCD][1-8]", channel)) and "relay-32" in capabilities
    if module_type == "LCM":
        if re.fullmatch(r"[AB][1-8]", channel):
            return "relay-32" in capabilities or "lighting" in capabilities
        if re.fullmatch(r"10-[1-8]", channel):
            return "analog-out-8" in capabilities
        if re.fullmatch(r"HV-[1-4]", channel):
            return "high-voltage-dimmer" in capabilities or "lighting" in capabilities
        return False
    if module_type == "SIM":
        if re.fullmatch(r"A[1-8]", channel):
            return "hexa-aio" in capabilities
        if re.fullmatch(r"DIO[1-4]", channel):
            return "hexa-dio" in capabilities
        if re.fullmatch(r"SW[1-3]", channel):
            return "hexa-12v-switching" in capabilities
        if re.fullmatch(r"CAN[0-2]", channel):
            return "hexa-can" in capabilities or "rmc-can" in capabilities
        return False
    return False


async def _module_for_binding(conn, identifier: str | int, channel: str | None) -> dict[str, Any]:
    text, device_id = _module_selector(identifier)
    row = await conn.fetchrow(
        """
        SELECT id, hostname, module_type, device_id
        FROM modules
        WHERE id::text=$1
           OR hostname=$1
           OR ($2::text IS NOT NULL AND device_id=$2)
        """,
        text,
        device_id,
    )
    if not row:
        raise NotFoundError(f"module {identifier}")
    capability_rows = await conn.fetch(
        "SELECT capability FROM module_capabilities WHERE module_id=$1",
        row["id"],
    )
    capabilities = _capability_names(capability_rows)
    normalized_channel = _normalize_channel(channel)
    if not _module_supports_channel(row["module_type"], normalized_channel, capabilities):
        caps = ", ".join(sorted(capabilities)) or "none"
        raise ValidationError(
            f"module {row['hostname']} does not declare support for channel {normalized_channel or '<none>'} "
            f"({row['module_type']} capabilities: {caps})"
        )
    return {
        "id": int(row["id"]),
        "hostname": row["hostname"],
        "module_type": row["module_type"],
        "device_id": row["device_id"],
        "channel": normalized_channel,
        "capabilities": capabilities,
    }


async def _ensure_no_active_binding_conflict(
    conn,
    *,
    module_id: int,
    channel: str | None,
    binding_type: str,
    exclude_binding_id: int | None = None,
) -> None:
    row = await conn.fetchrow(
        """
        SELECT id
        FROM device_bindings
        WHERE module_id=$1
          AND enabled=true
          AND ($4::bigint IS NULL OR id<>$4)
          AND (
                ($2::text IS NOT NULL AND channel=$2)
             OR ($2::text IS NULL AND channel IS NULL AND binding_type=$3)
          )
        LIMIT 1
        """,
        module_id,
        channel,
        binding_type,
        exclude_binding_id,
    )
    if row:
        raise ValidationError("active binding conflicts with an existing physical assignment")


async def audit_event(
    conn,
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str | None,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    details: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO device_management_events(
            actor, action, target_type, target_id, before_state, after_state, details
        )
        VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb)
        """,
        actor,
        action,
        target_type,
        target_id,
        _json_dumps(before_state) if before_state is not None else None,
        _json_dumps(after_state) if after_state is not None else None,
        _json_dumps(details or {}),
    )


async def list_modules() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM modules
            ORDER BY module_type, hostname
            """
        )
        module_ids = [int(row["id"]) for row in rows]
        capability_rows = await conn.fetch(
            """
            SELECT module_id, capability, details, first_seen_at, updated_at
            FROM module_capabilities
            WHERE module_id=ANY($1::bigint[])
            ORDER BY capability
            """,
            module_ids,
        ) if module_ids else []
    by_module: dict[int, list[dict[str, Any]]] = {module_id: [] for module_id in module_ids}
    for row in capability_rows:
        by_module.setdefault(int(row["module_id"]), []).append({
            "capability": row["capability"],
            "details": _wire_value(row["details"] or {}),
            "first_seen_at": _wire_value(row["first_seen_at"]),
            "updated_at": _wire_value(row["updated_at"]),
        })
    return [_module_summary(row, by_module.get(int(row["id"]), [])) for row in rows]


async def get_module(identifier: str | int) -> dict[str, Any]:
    text, device_id = _module_selector(identifier)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM modules
            WHERE id::text=$1
               OR hostname=$1
               OR ($2::text IS NOT NULL AND device_id=$2)
            """,
            text,
            device_id,
        )
        if not row:
            raise NotFoundError(str(identifier))
        capability_rows = await conn.fetch(
            """
            SELECT capability, details, first_seen_at, updated_at
            FROM module_capabilities
            WHERE module_id=$1
            ORDER BY capability
            """,
            row["id"],
        )
    capabilities = [
        {
            "capability": r["capability"],
            "details": _wire_value(r["details"] or {}),
            "first_seen_at": _wire_value(r["first_seen_at"]),
            "updated_at": _wire_value(r["updated_at"]),
        }
        for r in capability_rows
    ]
    return _module_summary(row, capabilities)


async def list_logical_devices() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.*, r.name AS room
            FROM logical_devices d
            LEFT JOIN rooms r ON r.id=d.room_id
            ORDER BY d.logical_name
            """
        )
    return [_logical_device(row) for row in rows]


async def create_logical_device(
    *,
    logical_name: str,
    device_class: str,
    actor: str,
    room_id: int | None = None,
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            row = await conn.fetchrow(
                """
                INSERT INTO logical_devices(logical_name, room_id, device_class, enabled, metadata)
                VALUES($1,$2,$3,$4,$5::jsonb)
                RETURNING *, NULL::text AS room
                """,
                logical_name,
                room_id,
                device_class,
                enabled,
                _json_dumps(metadata),
            )
            after = _logical_device(row)
            await audit_event(
                conn,
                actor=actor,
                action="logical_device.create",
                target_type="logical_device",
                target_id=str(row["id"]),
                before_state=None,
                after_state=after,
            )
    return after


async def update_logical_device(
    logical_name: str,
    *,
    actor: str,
    new_logical_name: str | None = None,
    device_class: str | None = None,
    room_id: int | None | object = UNSET,
    enabled: bool | None = None,
    maintenance_locked: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            before_row = await conn.fetchrow(
                "SELECT *, NULL::text AS room FROM logical_devices WHERE logical_name=$1 FOR UPDATE",
                logical_name,
            )
            if not before_row:
                raise NotFoundError(logical_name)
            before = _logical_device(before_row)
            room_was_supplied = room_id is not UNSET
            row = await conn.fetchrow(
                """
                UPDATE logical_devices
                SET logical_name=COALESCE($2, logical_name),
                    device_class=COALESCE($3, device_class),
                    room_id=CASE WHEN $4::boolean THEN $5::bigint ELSE room_id END,
                    enabled=COALESCE($6, enabled),
                    maintenance_locked=COALESCE($7, maintenance_locked),
                    metadata=COALESCE($8::jsonb, metadata)
                WHERE logical_name=$1
                RETURNING *, NULL::text AS room
                """,
                logical_name,
                new_logical_name,
                device_class,
                room_was_supplied,
                None if room_id is UNSET else room_id,
                enabled,
                maintenance_locked,
                _json_dumps(metadata) if metadata is not None else None,
            )
            after = _logical_device(row)
            await audit_event(
                conn,
                actor=actor,
                action="logical_device.update",
                target_type="logical_device",
                target_id=str(row["id"]),
                before_state=before,
                after_state=after,
            )
    return after


async def list_bindings() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.*, d.logical_name, m.hostname, m.device_id, m.module_type
            FROM device_bindings b
            JOIN logical_devices d ON d.id=b.logical_device_id
            JOIN modules m ON m.id=b.module_id
            ORDER BY d.logical_name, b.binding_type, b.id
            """
        )
    return [_binding(row) for row in rows]


async def resolve_module_id(conn, identifier: str | int) -> int:
    text, device_id = _module_selector(identifier)
    row = await conn.fetchrow(
        """
        SELECT id
        FROM modules
        WHERE id::text=$1
           OR hostname=$1
           OR ($2::text IS NOT NULL AND device_id=$2)
        """,
        text,
        device_id,
    )
    if not row:
        raise NotFoundError(f"module {identifier}")
    return int(row["id"])


async def create_binding(
    *,
    logical_name: str,
    module_identifier: str | int,
    channel: str | None,
    actor: str,
    binding_type: str = "primary",
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            logical = await conn.fetchrow(
                "SELECT id FROM logical_devices WHERE logical_name=$1",
                logical_name,
            )
            if not logical:
                raise NotFoundError(f"logical device {logical_name}")
            module = await _module_for_binding(conn, module_identifier, channel)
            if enabled:
                await _ensure_no_active_binding_conflict(
                    conn,
                    module_id=module["id"],
                    channel=module["channel"],
                    binding_type=binding_type,
                )
            row = await conn.fetchrow(
                """
                INSERT INTO device_bindings(
                    logical_device_id, module_id, channel, binding_type, enabled, metadata
                )
                VALUES($1,$2,$3,$4,$5,$6::jsonb)
                RETURNING *
                """,
                logical["id"],
                module["id"],
                module["channel"],
                binding_type,
                enabled,
                _json_dumps(metadata),
            )
            joined = await conn.fetchrow(
                """
                SELECT b.*, d.logical_name, m.hostname, m.device_id, m.module_type
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                JOIN modules m ON m.id=b.module_id
                WHERE b.id=$1
                """,
                row["id"],
            )
            after = _binding(joined)
            await audit_event(
                conn,
                actor=actor,
                action="binding.create",
                target_type="device_binding",
                target_id=str(row["id"]),
                before_state=None,
                after_state=after,
            )
    return after


async def update_binding(
    binding_id: int,
    *,
    actor: str,
    channel: str | None = None,
    binding_type: str | None = None,
    enabled: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            before_row = await conn.fetchrow(
                """
                SELECT b.*, d.logical_name, m.hostname, m.device_id, m.module_type
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                JOIN modules m ON m.id=b.module_id
                WHERE b.id=$1
                FOR UPDATE
                """,
                binding_id,
            )
            if not before_row:
                raise NotFoundError(str(binding_id))
            before = _binding(before_row)
            next_channel = _normalize_channel(channel) if channel is not None else before["channel"]
            next_binding_type = binding_type or before["binding_type"]
            next_enabled = enabled if enabled is not None else before["enabled"]
            module = await _module_for_binding(conn, before["module_id"], next_channel)
            if next_enabled:
                await _ensure_no_active_binding_conflict(
                    conn,
                    module_id=module["id"],
                    channel=module["channel"],
                    binding_type=next_binding_type,
                    exclude_binding_id=binding_id,
                )
            await conn.execute(
                """
                UPDATE device_bindings
                SET channel=$2,
                    binding_type=$3,
                    enabled=$4,
                    metadata=COALESCE($5::jsonb, metadata)
                WHERE id=$1
                """,
                binding_id,
                module["channel"],
                next_binding_type,
                next_enabled,
                _json_dumps(metadata) if metadata is not None else None,
            )
            after_row = await conn.fetchrow(
                """
                SELECT b.*, d.logical_name, m.hostname, m.device_id, m.module_type
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                JOIN modules m ON m.id=b.module_id
                WHERE b.id=$1
                """,
                binding_id,
            )
            after = _binding(after_row)
            await audit_event(
                conn,
                actor=actor,
                action="binding.update",
                target_type="device_binding",
                target_id=str(binding_id),
                before_state=before,
                after_state=after,
            )
    return after
