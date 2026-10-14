from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
from pathlib import Path
from datetime import date, datetime
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
from homecontrol_identity import InvalidDeviceId, maybe_normalize_device_id

from . import db
from . import storage
from .settings import settings

module_infra = __import__("importlib").import_module("07_servises.common.module_infra")


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


def _state_payload(module: dict[str, Any]) -> dict[str, Any]:
    state = _json_value(module.get("last_state") or {})
    return state if isinstance(state, dict) else {}


def _nested_state(module: dict[str, Any]) -> dict[str, Any]:
    state = _state_payload(module)
    nested = state.get("state")
    if isinstance(nested, dict):
        return nested
    return state


def _operational_role(module: dict[str, Any]) -> str:
    nested = _nested_state(module)
    role = nested.get("lab_role") or nested.get("operational_role") or nested.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip().upper()
    return str(module.get("module_type") or "UNASSIGNED").upper()


def _channel_display_name(row) -> str:
    metadata = _wire_value(row["logical_metadata"] or {})
    if isinstance(metadata, dict) and metadata.get("channel_name"):
        return str(metadata["channel_name"])
    return row["logical_name"] or ""


def _rcm_channel_ids() -> list[str]:
    return [f"{bank}{channel}" for bank in ("A", "B", "C", "D") for channel in range(1, 9)]


def _lcm_light_channels() -> list[str]:
    return [f"A{channel}" for channel in range(1, 9)]


def _lcm_dimmer_channels() -> list[str]:
    return [f"10-{channel}" for channel in range(1, 11)] + [f"HV-{channel}" for channel in range(1, 5)]


def _lcm_channel_ids() -> list[str]:
    return _lcm_light_channels() + _lcm_dimmer_channels()


def rcm_config_from_channels(channels: list[dict[str, Any]]) -> dict[str, Any]:
    by_channel = {item["channel"]: item for item in channels}
    rows = []
    for channel in _rcm_channel_ids():
        item = by_channel.get(channel) or {}
        rows.append({
            "channel": channel,
            "name": item.get("name", ""),
            "on": bool(item.get("value") is True),
            "lockout": bool(item.get("maintenance_locked")),
        })
    return {"channels": rows}


def lcm_config_from_channels(channels: list[dict[str, Any]]) -> dict[str, Any]:
    by_channel = {item["channel"]: item for item in channels}
    rows = []
    for channel in _lcm_channel_ids():
        item = by_channel.get(channel) or {}
        is_dimmer = channel in _lcm_dimmer_channels()
        rows.append({
            "channel": channel,
            "name": item.get("name", ""),
            "type": item.get("type_label") or item.get("type") or module_infra.lcm_channel_type(channel),
            "lockout": bool(item.get("maintenance_locked")),
            "emergency_lighting": bool(item.get("emergency_lighting")),
            "max_intensity": int(item.get("max_intensity", 100)) if is_dimmer else None,
            "fade_seconds": float(item.get("fade_seconds", 3.0)) if is_dimmer else None,
            "hardware_id": item.get("hardware_id") or module_infra.lcm_hardware_id(channel),
        })
    return {"channels": rows}


async def mirror_module_configuration(module_type: str, hostname: str, config: dict[str, Any]) -> dict[str, Any]:
    logical_id = str(hostname)
    store = module_infra.LocalConfigStore(storage.storage_root(), module_type, logical_id)
    try:
        if module_type == "RCM":
            csv_meta = store.save_rcm_csv(config["channels"])
        elif module_type == "LCM":
            csv_meta = store.save_lcm_csv(config["channels"])
        else:
            csv_meta = {"channel_count": 0, "revision": module_infra.stable_revision(config)}
        package = module_infra.build_config_package(module_type, logical_id, config, revision=csv_meta["revision"])
        json_meta = store.save_json(package)
    except OSError as exc:
        return {
            "state": "storage_unavailable",
            "module_type": module_type,
            "logical_id": logical_id,
            "reason": str(exc),
            "updated_at": module_infra.utc_ts(),
        }
    sync = {
        "state": "stored",
        "module_type": module_type,
        "logical_id": logical_id,
        "revision": package["revision"],
        "checksum": package["checksum"],
        "csv": csv_meta,
        "json": {"path": str(store.path(".json")), "revision": json_meta["revision"]},
        "updated_at": module_infra.utc_ts(),
    }
    try:
        from .registry import registry
        ack = await registry.config_by_hostname(logical_id, {"package": package, "base_revision": None})
        sync["ack"] = ack
        sync["state"] = "synchronized" if ack.get("ok") else "ack_failed"
    except Exception as exc:
        sync["state"] = "pending_retry"
        sync["reason"] = str(exc)
    state_path = storage.storage_root() / ".state" / "config-sync" / f"{logical_id}.json"
    module_infra.atomic_write_text(state_path, json.dumps(sync, indent=2, sort_keys=True))
    return sync


def _sim_analog_channels() -> list[str]:
    return [f"AI-{channel}" for channel in range(1, 11)]


def _sim_legacy_analog_channel(channel: str) -> str | None:
    match = re.fullmatch(r"AI-(10|[1-9])", channel)
    if not match:
        return None
    index = int(match.group(1))
    return f"A{index}" if index <= 8 else None


def _relay_value(last_state: dict[str, Any], channel: str) -> bool | None:
    nested = last_state.get("state") if isinstance(last_state.get("state"), dict) else last_state
    relays = nested.get("relays") if isinstance(nested, dict) else None
    if not isinstance(relays, dict):
        return None
    candidates = (channel, channel.lower(), str(_rcm_channel_ids().index(channel) + 1))
    for key in candidates:
        if key not in relays:
            continue
        value = relays[key]
        if isinstance(value, dict):
            for field in ("on", "value", "active", "state"):
                if field in value:
                    return bool(value[field])
        return bool(value)
    return None


def _dimmer_percent(last_state: dict[str, Any], channel: str) -> float | None:
    nested = last_state.get("state") if isinstance(last_state.get("state"), dict) else last_state
    for group in ("hv_dimmers", "lv_dimmers", "dimmers"):
        values = nested.get(group) if isinstance(nested, dict) else None
        if not isinstance(values, dict) or channel not in values:
            continue
        value = values[channel]
        if isinstance(value, dict):
            raw = value.get("percent", value.get("value"))
        else:
            raw = value
        if raw is None:
            return None
        return float(raw)
    return None


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


def _metadata_value(*metadata: Any, keys: tuple[str, ...]) -> Any:
    for item in metadata:
        clean = _wire_value(item or {})
        if not isinstance(clean, dict):
            continue
        for key in keys:
            value = clean.get(key)
            if value not in (None, ""):
                return value
    return None


def _severity_rank(value: str | None) -> int:
    order = {
        "critical": 0,
        "fatal": 0,
        "error": 1,
        "fault": 1,
        "warning": 2,
        "warn": 2,
        "offline": 2,
        "stale": 3,
        "info": 4,
        "unknown": 5,
    }
    return order.get(str(value or "unknown").lower(), 5)


def _conflict_supervisor_from_status(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "Unavailable",
            "available": False,
            "reason": "Conflict heartbeat status response was not structured data",
        }
    registry = payload.get("status", {}).get("registry") if isinstance(payload.get("status"), dict) else None
    if not isinstance(registry, dict):
        return {
            "status": "Unavailable",
            "available": False,
            "reason": "Conflict status did not include a heartbeat registry",
            "host": settings.conflict_heartbeat_host,
            "port": settings.conflict_heartbeat_port,
        }
    peer = registry.get(settings.hcm_heartbeat_device_id)
    if not isinstance(peer, dict):
        return {
            "status": "Unknown",
            "available": True,
            "reason": "Conflict registry does not include the configured HCM heartbeat identity",
            "host": settings.conflict_heartbeat_host,
            "port": settings.conflict_heartbeat_port,
            "conflict_device_id": payload.get("device_id"),
            "hcm_device_id": settings.hcm_heartbeat_device_id,
        }
    age = peer.get("last_seen_seconds_ago")
    try:
        age_seconds = float(age) if age is not None else None
    except (TypeError, ValueError):
        age_seconds = None
    online = peer.get("online")
    active_fault = peer.get("active_fault")
    conflict_health = payload.get("health", {}) if isinstance(payload.get("health"), dict) else {}
    conflict_status = payload.get("status", {}) if isinstance(payload.get("status"), dict) else {}
    conflict_healthy = conflict_health.get("state") == "healthy" and conflict_status.get("state") == "operational"
    if online is False:
        status = "Offline"
        reason = "Conflict registry marks the HCM heartbeat peer offline"
    elif online is True and age_seconds is not None and age_seconds <= settings.conflict_heartbeat_timeout_s and not active_fault and conflict_healthy:
        status = "Healthy"
        reason = "Conflict registry has a recent HCM heartbeat acknowledgement"
    elif online is True:
        status = "Degraded"
        reason = "Conflict registry is valid but acknowledgement age, peer fault, or supervisor health is abnormal"
    else:
        status = "Unknown"
        reason = "Conflict registry does not provide a confirmed online/offline state"
    return {
        "status": status,
        "available": True,
        "reason": reason,
        "host": settings.conflict_heartbeat_host,
        "port": settings.conflict_heartbeat_port,
        "protocol": settings.conflict_heartbeat_protocol,
        "conflict_device_id": payload.get("device_id"),
        "conflict_hostname": payload.get("hostname"),
        "hcm_device_id": settings.hcm_heartbeat_device_id,
        "hcm_hostname": peer.get("hostname"),
        "last_ack_age_seconds": age_seconds,
        "last_sequence": peer.get("last_sequence"),
        "peer_online": online,
        "peer_health": peer.get("health", {}).get("state") if isinstance(peer.get("health"), dict) else None,
        "peer_status": peer.get("status", {}).get("state") if isinstance(peer.get("status"), dict) else None,
        "active_fault": active_fault,
    }


async def conflict_supervisor_status() -> dict[str, Any]:
    if not settings.conflict_heartbeat_enabled:
        return {
            "status": "Unavailable",
            "available": False,
            "reason": "Conflict heartbeat status is disabled in HCM settings",
        }
    url = f"http://{settings.conflict_heartbeat_host}:{settings.conflict_heartbeat_port}/status"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "status": "Unavailable",
            "available": False,
            "reason": f"Conflict heartbeat status could not be verified: {exc}",
            "host": settings.conflict_heartbeat_host,
            "port": settings.conflict_heartbeat_port,
        }
    return _conflict_supervisor_from_status(payload)


def _health_fault_items(module: dict[str, Any]) -> list[dict[str, Any]]:
    health = _wire_value(module.get("last_health") or {})
    if not isinstance(health, dict):
        return []
    faults = health.get("faults")
    if not isinstance(faults, list):
        return []
    items = []
    for index, fault in enumerate(faults, start=1):
        if isinstance(fault, str):
            fault = {"code": fault}
        if not isinstance(fault, dict):
            continue
        if fault.get("active") is False or fault.get("cleared") is True:
            continue
        code = fault.get("code") or fault.get("name") or fault.get("type") or f"health_fault_{index}"
        items.append({
            "source": "module_health",
            "severity": str(fault.get("severity") or "warning"),
            "module": module.get("hostname"),
            "component": fault.get("component") or fault.get("type") or "module health",
            "code": str(code),
            "description": fault.get("description") or fault.get("detail") or fault.get("message") or str(code),
            "reported_at": _wire_value(fault.get("reported_at") or fault.get("timestamp") or fault.get("updated_at")),
            "active": True,
        })
    return items


def _sim_rmc_fault_items(module: dict[str, Any]) -> list[dict[str, Any]]:
    state = _nested_state(module)
    nodes = state.get("rmc_nodes")
    if not isinstance(nodes, dict):
        return []
    items = []
    for node_key, node in nodes.items():
        if not isinstance(node, dict):
            continue
        faults = node.get("faults") or node.get("sensor_faults") or []
        active = bool(node.get("fault_active") or node.get("any_sensor_fault") or faults)
        if not active:
            continue
        if isinstance(faults, str):
            faults = [faults]
        if not isinstance(faults, list) or not faults:
            faults = ["rmc_fault"]
        for fault in faults:
            code = str(fault)
            items.append({
                "source": "sim_rmc_state",
                "severity": "warning",
                "module": module.get("hostname"),
                "component": node.get("rmc_id") or f"RMC {node.get('address', node_key)}",
                "code": code,
                "description": code,
                "reported_at": _wire_value(node.get("last_heartbeat") or node.get("last_seen")),
                "active": True,
            })
    return items


def _explicit_emergency_url(module: dict[str, Any]) -> str | None:
    payloads = [
        module.get("last_health"),
        module.get("last_state"),
        _nested_state(module),
    ]
    for payload in payloads:
        data = _wire_value(payload or {})
        if not isinstance(data, dict):
            continue
        candidates = [
            data.get("emergency_interface_url"),
            data.get("emergency_url"),
            (data.get("emergency_interface") or {}).get("url") if isinstance(data.get("emergency_interface"), dict) else None,
            (data.get("management") or {}).get("emergency_url") if isinstance(data.get("management"), dict) else None,
        ]
        for candidate in candidates:
            if candidate:
                return str(candidate)
    return None


def _validated_emergency_url(module: dict[str, Any]) -> tuple[str | None, str]:
    candidate = _explicit_emergency_url(module)
    if not candidate:
        return None, "Emergency interface not verified"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None, "Emergency URL scheme is not allowed"
    host = parsed.hostname
    if not host:
        return None, "Emergency URL host is missing"
    allowed_hosts = {str(module.get("ip_address") or ""), str(module.get("hostname") or "")}
    allowed_hosts = {item.lower() for item in allowed_hosts if item}
    if host.lower() not in allowed_hosts:
        return None, "Emergency URL host does not match the registered module address"
    return candidate, "Verified explicit module emergency URL"


def _emergency_capability(module: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Read only the authenticated module's structured emergency capability."""
    payload = _state_payload(module)
    candidates = [payload.get("emergency_ui"), _nested_state(module).get("emergency_ui")]
    capability = next((item for item in candidates if isinstance(item, dict)), None)
    if not capability:
        return None, "Emergency service was not advertised"
    if capability.get("enabled") is not True or capability.get("available") is not True:
        return None, "Emergency service is advertised as unavailable"
    try:
        valid_port = int(capability.get("port", 0)) == 6010
    except (TypeError, ValueError):
        valid_port = False
    if capability.get("protocol") != "http" or not valid_port:
        return None, "Emergency service advertisement is invalid"
    if capability.get("config_path") != "/config" or capability.get("health_path") != "/health":
        return None, "Emergency service paths are not approved"
    return capability, "Emergency service advertised"


async def _probe_emergency_interface(module: dict[str, Any]) -> dict[str, Any]:
    capability, reason = _emergency_capability(module)
    result = {
        "available": False,
        "status": "unknown" if "not advertised" in reason else "unavailable",
        "url": None,
        "reason": reason,
    }
    address = str(module.get("ip_address") or "").strip()
    if not capability or not address or not module.get("online"):
        return result
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return {**result, "reason": "Registered module address is invalid"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5), follow_redirects=False) as client:
            response = await client.get(f"http://{address}:6010/health")
        data = response.json()
        identity = data.get("identity") if isinstance(data, dict) else None
        if response.status_code != 200 or not isinstance(identity, dict):
            raise ValueError("invalid health response")
        if str(identity.get("device_id") or "").lower() != str(module.get("device_id") or "").lower():
            raise ValueError("health identity mismatch")
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        return {**result, "reason": "Emergency health probe failed"}
    return {
        "available": True,
        "status": "available",
        "url": f"http://{address}:6010{capability['config_path']}",
        "reason": "Verified module-advertised emergency service",
    }


def _host_interfaces_from_status_file() -> tuple[list[dict[str, Any]], str | None]:
    path = settings.host_network_status_file
    if not path:
        return [], "Host network status provider is not configured"
    path = Path(path)
    if not path.exists():
        return [], "Configured host network status file is unavailable"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return [], "Configured host network status file could not be read"
    interfaces = data.get("interfaces") if isinstance(data, dict) else None
    if not isinstance(interfaces, list):
        return [], "Configured host network status file has no interface list"
    updated_at = data.get("updated_at") if isinstance(data, dict) else None
    try:
        if updated_at is None or time.time() - float(updated_at) > 120:
            return [], "Configured host network status is stale"
    except (TypeError, ValueError):
        return [], "Configured host network status timestamp is invalid"
    normalized = []
    for item in interfaces:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "name": item.get("name") or item.get("interface") or "Unknown",
            "ipv4": item.get("ipv4") or [],
            "ipv6": item.get("ipv6") or [],
            "status": item.get("status") or "Unknown",
            "network": item.get("network") or item.get("prefix") or None,
            "default_route": item.get("default_route") if isinstance(item.get("default_route"), dict) else None,
        })
    return normalized, None


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
        if re.fullmatch(r"A[1-8]", channel):
            return "relay-8" in capabilities or "relay-32" in capabilities or "lighting" in capabilities
        if re.fullmatch(r"10-[1-8]", channel):
            return "analog-out-8" in capabilities or "analog-out-10" in capabilities or "lighting" in capabilities
        if re.fullmatch(r"10-(?:9|10)", channel):
            return "analog-out-10" in capabilities or "lighting" in capabilities
        if re.fullmatch(r"HV-[1-4]", channel):
            return "high-voltage-dimmer" in capabilities or "lighting" in capabilities
        return False
    if module_type == "SIM":
        if re.fullmatch(r"A[1-8]", channel) or re.fullmatch(r"AI-(10|[1-9])", channel):
            return "hexa-aio" in capabilities
        if re.fullmatch(r"RMC:[A-Z0-9_-]+:[0-9A-F]+", channel):
            return "rmc-can" in capabilities
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


async def get_device_admin(identifier: str | int) -> dict[str, Any]:
    module = await get_module(identifier)
    effective_role = _operational_role(module)
    nested = _nested_state(module)
    return {
        "module": module,
        "effective_role": effective_role,
        "role_source": "reported_state" if effective_role != module["module_type"] else "registered_module_type",
        "simulation": nested.get("simulation"),
        "physical_outputs_enabled": nested.get("physical_outputs_enabled"),
        "config_sync": nested.get("config_sync") if isinstance(nested.get("config_sync"), dict) else None,
        "replacement_ready": {
            "supported": True,
            "automatic_reassignment_enabled": False,
            "note": "Logical identities are preserved separately from physical device IDs; replacement is intentionally manual.",
        },
    }


async def get_rcm_channels(identifier: str | int) -> dict[str, Any]:
    module = await get_device_admin(identifier)
    if module["effective_role"] != "RCM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the RCM role")
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.id AS binding_id,
                   b.channel,
                   b.enabled AS binding_enabled,
                   d.id AS logical_device_id,
                   d.logical_name,
                   d.enabled AS logical_enabled,
                   d.maintenance_locked,
                   d.metadata AS logical_metadata
            FROM device_bindings b
            JOIN logical_devices d ON d.id=b.logical_device_id
            WHERE b.module_id=$1
              AND b.channel=ANY($2::text[])
            ORDER BY b.channel, b.id
            """,
            module["module"]["id"],
            _rcm_channel_ids(),
        )
    by_channel = {row["channel"]: row for row in rows}
    online = bool(module["module"]["online"] or module["module"]["control_session_online"])
    control_online = bool(module["module"]["control_session_online"])
    physical_outputs_enabled = module.get("physical_outputs_enabled")
    inhibited = physical_outputs_enabled is False
    last_state = _state_payload(module["module"])
    channels = []
    for index, channel in enumerate(_rcm_channel_ids(), start=1):
        row = by_channel.get(channel)
        disabled_reason = None
        if not row:
            disabled_reason = "No logical binding"
        elif not row["logical_enabled"] or not row["binding_enabled"]:
            disabled_reason = "Binding disabled"
        elif row["maintenance_locked"]:
            disabled_reason = "Maintenance lockout"
        elif not control_online:
            disabled_reason = "No authenticated control session"
        elif inhibited:
            disabled_reason = "Physical outputs disabled"
        channels.append({
            "number": index,
            "channel": channel,
            "binding_id": int(row["binding_id"]) if row else None,
            "logical_device_id": int(row["logical_device_id"]) if row else None,
            "logical_name": row["logical_name"] if row else None,
            "name": _channel_display_name(row) if row else "",
            "bound": row is not None,
            "enabled": bool(row and row["logical_enabled"] and row["binding_enabled"]),
            "maintenance_locked": bool(row["maintenance_locked"]) if row else False,
            "online": online,
            "control_session_online": control_online,
            "physical_outputs_enabled": physical_outputs_enabled,
            "value": _relay_value(last_state, channel),
            "control_enabled": disabled_reason is None,
            "disabled_reason": disabled_reason,
        })
    return {"device": module, "channels": channels}


async def update_rcm_channel_name(
    identifier: str | int,
    channel: str,
    *,
    name: str,
    actor: str,
) -> dict[str, Any]:
    normalized_channel = _normalize_channel(channel)
    if normalized_channel not in _rcm_channel_ids():
        raise ValidationError("invalid RCM channel")
    module = await get_device_admin(identifier)
    if module["effective_role"] != "RCM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the RCM role")
    async with db.acquire() as conn:
        async with _transaction(conn):
            before_row = await conn.fetchrow(
                """
                SELECT d.*, NULL::text AS room
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                WHERE b.module_id=$1
                  AND b.channel=$2
                FOR UPDATE
                """,
                module["module"]["id"],
                normalized_channel,
            )
            if not before_row:
                raise NotFoundError(f"{module['module']['hostname']} {normalized_channel}")
            before = _logical_device(before_row)
            row = await conn.fetchrow(
                """
                UPDATE logical_devices
                SET metadata=jsonb_set(metadata, '{channel_name}', to_jsonb($2::text), true)
                WHERE id=$1
                RETURNING *, NULL::text AS room
                """,
                before_row["id"],
                name.strip(),
            )
            after = _logical_device(row)
            await audit_event(
                conn,
                actor=actor,
                action="rcm_channel.name_update",
                target_type="logical_device",
                target_id=str(row["id"]),
                before_state=before,
                after_state=after,
                details={"module": module["module"]["hostname"], "channel": normalized_channel},
            )
    result = await get_rcm_channels(module["module"]["hostname"])
    result["config_sync"] = await mirror_module_configuration("RCM", module["module"]["hostname"], rcm_config_from_channels(result["channels"]))
    return result


async def get_lcm_channels(identifier: str | int) -> dict[str, Any]:
    module = await get_device_admin(identifier)
    if module["effective_role"] != "LCM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the LCM role")
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.id AS binding_id,
                   b.channel,
                   b.enabled AS binding_enabled,
                   d.id AS logical_device_id,
                   d.logical_name,
                   d.enabled AS logical_enabled,
                   d.maintenance_locked,
                   d.metadata AS logical_metadata
            FROM device_bindings b
            JOIN logical_devices d ON d.id=b.logical_device_id
            WHERE b.module_id=$1
              AND b.channel=ANY($2::text[])
            ORDER BY b.channel, b.id
            """,
            module["module"]["id"],
            _lcm_channel_ids(),
        )
    online = bool(module["module"]["online"] or module["module"]["control_session_online"])
    control_online = bool(module["module"]["control_session_online"])
    last_state = _state_payload(module["module"])
    by_channel = {row["channel"]: row for row in rows}
    channels = []
    for index, channel in enumerate(_lcm_channel_ids(), start=1):
        row = by_channel.get(channel)
        channel_type = "Relay"
        if channel.startswith("10-"):
            channel_type = "0-10V"
        elif channel.startswith("HV-"):
            channel_type = "110V"
        position = index
        metadata = _wire_value(row["logical_metadata"] or {}) if row else {}
        if not isinstance(metadata, dict):
            metadata = {}
        is_dimmer = channel in _lcm_dimmer_channels()
        disabled_reason = None
        if not row:
            disabled_reason = "No logical binding"
        elif not row["logical_enabled"] or not row["binding_enabled"]:
            disabled_reason = "Binding disabled"
        elif row["maintenance_locked"]:
            disabled_reason = "Maintenance lockout"
        elif not control_online:
            disabled_reason = "No authenticated control session"
        percent = _dimmer_percent(last_state, channel) if is_dimmer else None
        channels.append({
            "number": position,
            "channel": channel,
            "kind": "dimmer" if is_dimmer else "light",
            "type": channel_type,
            "type_label": channel_type,
            "binding_id": int(row["binding_id"]) if row else None,
            "logical_device_id": int(row["logical_device_id"]) if row else None,
            "logical_name": row["logical_name"] if row else None,
            "name": _channel_display_name(row) if row else "",
            "bound": row is not None,
            "enabled": bool(row and row["logical_enabled"] and row["binding_enabled"]),
            "maintenance_locked": bool(row["maintenance_locked"]) if row else False,
            "emergency_lighting": bool(metadata.get("emergency_lighting")),
            "max_intensity": int(metadata.get("max_intensity", 100)),
            "fade_seconds": float(metadata.get("fade_seconds", 3)),
            "last_nonzero_percent": float(metadata.get("last_nonzero_percent", metadata.get("max_intensity", 100))),
            "online": online,
            "control_session_online": control_online,
            "value": (percent or 0) > 0 if is_dimmer else _relay_value(last_state, channel),
            "percent": percent,
            "control_enabled": disabled_reason is None,
            "disabled_reason": disabled_reason,
        })
    return {"device": module, "channels": channels}


async def update_lcm_channel_settings(
    identifier: str | int,
    channel: str,
    *,
    name: str,
    emergency_lighting: bool,
    max_intensity: int | None,
    fade_seconds: float | None,
    actor: str,
) -> dict[str, Any]:
    normalized_channel = _normalize_channel(channel)
    if normalized_channel not in _lcm_channel_ids():
        raise ValidationError("invalid LCM channel")
    module = await get_device_admin(identifier)
    if module["effective_role"] != "LCM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the LCM role")
    metadata_patch = {
        "channel_name": name.strip(),
        "emergency_lighting": bool(emergency_lighting),
    }
    if normalized_channel in _lcm_dimmer_channels():
        metadata_patch["max_intensity"] = 100 if max_intensity is None else int(max_intensity)
        metadata_patch["fade_seconds"] = 3 if fade_seconds is None else float(fade_seconds)
    async with db.acquire() as conn:
        async with _transaction(conn):
            before_row = await conn.fetchrow(
                """
                SELECT d.*, NULL::text AS room
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                WHERE b.module_id=$1
                  AND b.channel=$2
                FOR UPDATE
                """,
                module["module"]["id"],
                normalized_channel,
            )
            if not before_row:
                raise NotFoundError(f"{module['module']['hostname']} {normalized_channel}")
            before = _logical_device(before_row)
            before_metadata = before["metadata"] if isinstance(before["metadata"], dict) else {}
            next_metadata = {**before_metadata, **metadata_patch}
            row = await conn.fetchrow(
                """
                UPDATE logical_devices
                SET metadata=$2::jsonb
                WHERE id=$1
                RETURNING *, NULL::text AS room
                """,
                before_row["id"],
                _json_dumps(next_metadata),
            )
            after = _logical_device(row)
            await audit_event(
                conn,
                actor=actor,
                action="lcm_channel.settings_update",
                target_type="logical_device",
                target_id=str(row["id"]),
                before_state=before,
                after_state=after,
                details={"module": module["module"]["hostname"], "channel": normalized_channel},
            )
    result = await get_lcm_channels(module["module"]["hostname"])
    result["config_sync"] = await mirror_module_configuration("LCM", module["module"]["hostname"], lcm_config_from_channels(result["channels"]))
    return result


def _sim_state(module: dict[str, Any]) -> dict[str, Any]:
    state = _nested_state(module)
    return state if isinstance(state, dict) else {}


def _sim_can_loops(state: dict[str, Any]) -> list[dict[str, Any]]:
    can = state.get("can")
    if not isinstance(can, dict):
        hexa = state.get("hexa_board")
        can = hexa.get("can") if isinstance(hexa, dict) else None
    labels = [("A", "can0"), ("B", "can1"), ("C", "can2")]
    loops = []
    for friendly, fallback_interface in labels:
        item = None
        interface = fallback_interface
        if isinstance(can, dict):
            for name, candidate in can.items():
                if not isinstance(candidate, dict):
                    continue
                label = str(candidate.get("label") or name).upper()
                if name == fallback_interface or label in {f"CAN {friendly}", friendly}:
                    item = candidate
                    interface = name
                    break
        status = "Unknown"
        if isinstance(item, dict):
            raw_status = str(item.get("status", "")).strip().upper()
            if raw_status in {"ONLINE", "OFFLINE", "FAULT", "UNKNOWN"}:
                status = raw_status.title()
            elif item.get("fault") or item.get("bus_fault") or item.get("error"):
                status = "Fault"
            elif item.get("enabled") is False:
                status = "Offline"
            elif item.get("last_frame") or int(item.get("rx_count") or 0) > 0 or int(item.get("tx_count") or 0) > 0:
                status = "Online"
        loops.append({
            "label": friendly,
            "interface": interface,
            "status": status,
            "diagnostics": _wire_value(item or {}),
        })
    return loops


def _sim_rmc_id(node: dict[str, Any]) -> str:
    address = node.get("address")
    if address is None:
        address = node.get("node_id", node.get("id", "unknown"))
    interface = str(node.get("can_interface") or node.get("interface") or "unknown")
    return f"RMC:{interface}:{address}"


def _sim_node_status(node: dict[str, Any]) -> str:
    if node.get("fault_active") or node.get("any_sensor_fault"):
        return "Fault"
    if node.get("offline"):
        return "Offline"
    if node.get("stale"):
        return "Stale"
    if node.get("last_seen"):
        return "Online"
    return "Unknown"


def _measurement(value: Any, unit: str | None = None, *, stale: bool = False) -> dict[str, Any]:
    return {
        "value": value if value is not None else None,
        "unit": unit,
        "status": "Stale" if stale and value is not None else "Unknown" if value is None else "OK",
    }


def _binding_metadata(row) -> dict[str, Any]:
    metadata = _wire_value(row["logical_metadata"] or {}) if row else {}
    return metadata if isinstance(metadata, dict) else {}


def _matches_rmc_binding(row, rmc_id: str, node: dict[str, Any]) -> bool:
    channel = row["channel"]
    metadata = _binding_metadata(row)
    if channel == rmc_id:
        return True
    if metadata.get("rmc_id") == rmc_id:
        return True
    address = str(node.get("address", node.get("node_id", "")))
    interface = str(node.get("can_interface") or node.get("interface") or "")
    return str(metadata.get("can_address", metadata.get("node_id", ""))) == address and (
        not interface or str(metadata.get("can_interface", metadata.get("interface", ""))) == interface
    )


async def get_sim_dashboard(identifier: str | int) -> dict[str, Any]:
    module = await get_device_admin(identifier)
    if module["effective_role"] != "SIM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the SIM role")
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.id AS binding_id,
                   b.channel,
                   b.enabled AS binding_enabled,
                   b.metadata AS binding_metadata,
                   d.id AS logical_device_id,
                   d.logical_name,
                   d.room_id,
                   r.name AS room,
                   d.enabled AS logical_enabled,
                   d.metadata AS logical_metadata,
                   d.device_class
            FROM device_bindings b
            JOIN logical_devices d ON d.id=b.logical_device_id
            LEFT JOIN rooms r ON r.id=d.room_id
            WHERE b.module_id=$1
            ORDER BY b.channel, b.id
            """,
            module["module"]["id"],
        )
    state = _sim_state(module["module"])
    hexa = state.get("hexa_board") if isinstance(state.get("hexa_board"), dict) else {}
    aio = hexa.get("aio") if isinstance(hexa.get("aio"), dict) else {}
    raw_ai = aio.get("analog_inputs") if isinstance(aio.get("analog_inputs"), dict) else {}
    by_channel = {row["channel"]: row for row in rows}
    analog_inputs = []
    for index, channel in enumerate(_sim_analog_channels(), start=1):
        legacy = _sim_legacy_analog_channel(channel)
        row = by_channel.get(channel) or (by_channel.get(legacy) if legacy else None)
        raw = raw_ai.get(f"a{index}") or raw_ai.get(f"ai-{index}") or raw_ai.get(channel) or (raw_ai.get(legacy.lower()) if legacy else None)
        raw = raw if isinstance(raw, dict) else {}
        disabled_reason = None
        if not row:
            disabled_reason = "No logical binding"
        elif not row["logical_enabled"] or not row["binding_enabled"]:
            disabled_reason = "Binding disabled"
        value = raw.get("value")
        analog_inputs.append({
            "number": index,
            "channel": channel,
            "firmware_channel": legacy,
            "name": _channel_display_name(row) if row else "",
            "bound": row is not None,
            "binding_id": int(row["binding_id"]) if row else None,
            "logical_device_id": int(row["logical_device_id"]) if row else None,
            "logical_name": row["logical_name"] if row else None,
            "enabled": bool(row and row["logical_enabled"] and row["binding_enabled"]),
            "value": value if value is not None else None,
            "unit": raw.get("unit", "V") if raw else None,
            "status": raw.get("status") if raw else "Unknown",
            "source": raw.get("source") if raw else None,
            "config_enabled": disabled_reason is None,
            "disabled_reason": disabled_reason,
        })
    nodes = state.get("rmc_nodes") if isinstance(state.get("rmc_nodes"), dict) else {}
    rmcs = []
    for key, raw_node in sorted(nodes.items(), key=lambda item: str(item[0])):
        node = _wire_value(raw_node)
        if not isinstance(node, dict):
            continue
        node = {**node}
        node.setdefault("address", key)
        rmc_id = str(node.get("rmc_id") or _sim_rmc_id(node))
        row = next((candidate for candidate in rows if _matches_rmc_binding(candidate, rmc_id, node)), None)
        metadata = _binding_metadata(row)
        stale = bool(node.get("stale"))
        room_name = row["room"] if row and row["room"] else "Unassigned"
        rmcs.append({
            "id": rmc_id,
            "logical_identifier": row["logical_name"] if row else rmc_id,
            "name": metadata.get("rmc_name") or metadata.get("channel_name") or (row["logical_name"] if row else str(node.get("name") or rmc_id)),
            "bound": row is not None,
            "binding_id": int(row["binding_id"]) if row else None,
            "logical_device_id": int(row["logical_device_id"]) if row else None,
            "room_id": int(row["room_id"]) if row and row["room_id"] is not None else None,
            "room": room_name,
            "can_interface": node.get("can_interface") or node.get("interface"),
            "can_node_address": node.get("address"),
            "status": _sim_node_status(node),
            "last_seen": _wire_value(node.get("last_seen")),
            "last_heartbeat": _wire_value(node.get("last_heartbeat", node.get("last_seen") if node.get("last_frame_kind") == "heartbeat" else None)),
            "firmware_version": node.get("firmware_version"),
            "hardware_revision": node.get("hardware_revision"),
            "health_flags": node.get("status_flags"),
            "faults": node.get("faults", node.get("sensor_faults", [])),
            "readings": {
                "temperature_f": _measurement(node.get("temperature_f"), "F", stale=stale),
                "humidity_pct": _measurement(node.get("humidity_pct"), "%", stale=stale),
                "lux": _measurement(node.get("lux"), "lux", stale=stale),
                "aqi": _measurement(node.get("aqi"), None, stale=stale),
                "presence": _measurement(node.get("presence"), None, stale=stale),
            },
        })
    room_groups: dict[str, dict[str, Any]] = {}
    for rmc in rmcs:
        key = str(rmc["room_id"] or rmc["room"])
        room_groups.setdefault(key, {
            "room_id": rmc["room_id"],
            "room": rmc["room"],
            "rmcs": [],
        })["rmcs"].append(rmc)
    return {
        "device": module,
        "can_loops": _sim_can_loops(state),
        "room_clusters": list(room_groups.values()),
        "rmcs": rmcs,
        "analog_inputs": analog_inputs,
        "diagnostics": {
            "can": _wire_value(state.get("can") or hexa.get("can") or {}),
            "hexa_board_model": hexa.get("model"),
            "io_mode": state.get("io_mode"),
        },
    }


async def _update_bound_logical_metadata(
    *,
    module: dict[str, Any],
    channel: str,
    metadata_patch: dict[str, Any],
    actor: str,
    action: str,
) -> dict[str, Any]:
    async with db.acquire() as conn:
        async with _transaction(conn):
            before_row = await conn.fetchrow(
                """
                SELECT d.*, NULL::text AS room
                FROM device_bindings b
                JOIN logical_devices d ON d.id=b.logical_device_id
                WHERE b.module_id=$1
                  AND b.channel=$2
                FOR UPDATE
                """,
                module["module"]["id"],
                channel,
            )
            if not before_row:
                raise NotFoundError(f"{module['module']['hostname']} {channel}")
            before = _logical_device(before_row)
            before_metadata = before["metadata"] if isinstance(before["metadata"], dict) else {}
            next_metadata = {**before_metadata, **metadata_patch}
            row = await conn.fetchrow(
                """
                UPDATE logical_devices
                SET metadata=$2::jsonb
                WHERE id=$1
                RETURNING *, NULL::text AS room
                """,
                before_row["id"],
                _json_dumps(next_metadata),
            )
            after = _logical_device(row)
            await audit_event(
                conn,
                actor=actor,
                action=action,
                target_type="logical_device",
                target_id=str(row["id"]),
                before_state=before,
                after_state=after,
                details={"module": module["module"]["hostname"], "channel": channel},
            )
    return after


async def update_sim_rmc_name(identifier: str | int, rmc_id: str, *, name: str, actor: str) -> dict[str, Any]:
    module = await get_device_admin(identifier)
    if module["effective_role"] != "SIM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the SIM role")
    clean = str(rmc_id).strip()
    await _update_bound_logical_metadata(
        module=module,
        channel=clean,
        metadata_patch={"rmc_name": name.strip()},
        actor=actor,
        action="sim_rmc.name_update",
    )
    return await get_sim_dashboard(module["module"]["hostname"])


async def update_sim_analog_name(identifier: str | int, channel: str, *, name: str, actor: str) -> dict[str, Any]:
    module = await get_device_admin(identifier)
    if module["effective_role"] != "SIM":
        raise ValidationError(f"module {module['module']['hostname']} is not currently assigned the SIM role")
    normalized_channel = _normalize_channel(channel)
    if normalized_channel not in _sim_analog_channels():
        raise ValidationError("invalid SIM analog input")
    try_channels = [normalized_channel]
    legacy = _sim_legacy_analog_channel(normalized_channel)
    if legacy:
        try_channels.append(legacy)
    last_exc = None
    for candidate in try_channels:
        try:
            await _update_bound_logical_metadata(
                module=module,
                channel=candidate,
                metadata_patch={"channel_name": name.strip()},
                actor=actor,
                action="sim_analog.name_update",
            )
            return await get_sim_dashboard(module["module"]["hostname"])
        except NotFoundError as exc:
            last_exc = exc
    raise last_exc or NotFoundError(f"{module['module']['hostname']} {normalized_channel}")


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


async def dashboard_status() -> dict[str, Any]:
    conflict_status = await conflict_supervisor_status()
    async with db.acquire() as conn:
        lock_rows = await conn.fetch(
            """
            SELECT m.hostname AS module_hostname,
                   m.module_type,
                   d.logical_name,
                   d.device_class,
                   d.maintenance_locked,
                   d.metadata AS logical_metadata,
                   b.channel,
                   b.metadata AS binding_metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.maintenance_locked=true
              AND b.enabled=true
              AND b.channel IS NOT NULL
            ORDER BY m.hostname, b.channel, d.logical_name
            """
        )
        fault_rows = await conn.fetch(
            """
            SELECT f.id,
                   f.device_id,
                   f.module_uuid,
                   f.logical_device_id,
                   f.code,
                   f.severity,
                   f.details,
                   f.active,
                   f.created_at,
                   m.hostname AS module_hostname,
                   d.logical_name
            FROM faults f
            LEFT JOIN modules m
              ON (f.device_id IS NOT NULL AND m.device_id=f.device_id)
              OR (f.module_uuid IS NOT NULL AND m.module_uuid=f.module_uuid)
            LEFT JOIN logical_devices d ON d.id=f.logical_device_id
            WHERE f.active=true
            ORDER BY f.severity, f.created_at DESC, f.id DESC
            """
        )
        safety_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (event_type)
                   event_type,
                   active,
                   details,
                   created_at
            FROM safety_events
            ORDER BY event_type, created_at DESC, id DESC
            """
        )
        module_rows = await conn.fetch(
            """
            SELECT *
            FROM modules
            ORDER BY hostname
            """
        )

    lockouts = []
    for row in lock_rows:
        logical_metadata = _wire_value(row["logical_metadata"] or {})
        binding_metadata = _wire_value(row["binding_metadata"] or {})
        lockouts.append({
            "module": row["module_hostname"],
            "module_type": row["module_type"],
            "logical_name": row["logical_name"],
            "channel_name": _metadata_value(
                logical_metadata,
                binding_metadata,
                keys=("channel_name", "name", "label"),
            ) or row["logical_name"],
            "channel": row["channel"],
            "locked": bool(row["maintenance_locked"]),
            "reason": _metadata_value(
                logical_metadata,
                binding_metadata,
                keys=("maintenance_lock_reason", "maintenance_locked_reason", "lockout_reason"),
            ),
            "locked_at": _metadata_value(
                logical_metadata,
                binding_metadata,
                keys=("maintenance_locked_at", "locked_at", "lockout_at"),
            ),
        })

    faults = []
    for row in fault_rows:
        details = _wire_value(row["details"] or {})
        description = None
        component = None
        if isinstance(details, dict):
            description = details.get("description") or details.get("detail") or details.get("message")
            component = details.get("component") or details.get("subsystem")
        faults.append({
            "source": "faults",
            "severity": row["severity"],
            "module": row["module_hostname"],
            "component": component or row["logical_name"] or row["device_id"] or row["module_uuid"] or "HCM",
            "code": row["code"],
            "description": description or row["code"],
            "reported_at": _wire_value(row["created_at"]),
            "active": bool(row["active"]),
        })

    for row in safety_rows:
        if not row["active"]:
            continue
        details = _wire_value(row["details"] or {})
        faults.append({
            "source": "safety_events",
            "severity": "critical" if row["event_type"] == "fire" else "warning",
            "module": "HCM",
            "component": "safety",
            "code": row["event_type"],
            "description": details.get("reason") if isinstance(details, dict) and details.get("reason") else row["event_type"],
            "reported_at": _wire_value(row["created_at"]),
            "active": True,
        })

    modules = [_module_summary(row) for row in module_rows]
    for module in modules:
        state = str(module.get("supervision_state") or "").lower()
        if not module.get("online") or state in {"offline", "fault", "error"}:
            faults.append({
                "source": "module_supervision",
                "severity": "warning",
                "module": module.get("hostname"),
                "component": "supervision",
                "code": state or "offline",
                "description": f"Module supervision state is {module.get('supervision_state') or 'unknown'}",
                "reported_at": module.get("supervision_last_seen") or module.get("last_seen"),
                "active": True,
            })
        faults.extend(_health_fault_items(module))
        faults.extend(_sim_rmc_fault_items(module))

    faults.sort(key=lambda item: str(item.get("reported_at") or ""), reverse=True)
    faults.sort(key=lambda item: _severity_rank(item.get("severity")))
    return {
        "maintenance_lockouts": {
            "count": len(lockouts),
            "items": lockouts,
        },
        "active_faults": {
            "count": len(faults),
            "items": faults,
            "unsupported_sources": [
                "Historical output-arbitration log entries are not treated as current active faults.",
            ],
        },
        "conflict_supervisor": conflict_status,
    }


async def settings_network() -> dict[str, Any]:
    interfaces, unavailable_reason = _host_interfaces_from_status_file()
    modules = await list_modules()
    emergency_interfaces = await asyncio.gather(*(_probe_emergency_interface(module) for module in modules))
    module_rows = []
    for module, emergency_interface in zip(modules, emergency_interfaces):
        address = module.get("ip_address")
        address_source = "current" if module.get("online") and address else "last_known" if address else "unknown"
        module_rows.append({
            "hostname": module["hostname"],
            "module_type": module["module_type"],
            "effective_role": _operational_role(module),
            "ip_address": address,
            "address_source": address_source,
            "online": bool(module.get("online") or module.get("control_session_online")),
            "status": "Online" if module.get("online") or module.get("control_session_online") else "Offline",
            "last_seen": module.get("last_seen") or module.get("supervision_last_seen"),
            "emergency_interface": emergency_interface,
        })
    return {
        "host_interfaces": {
            "available": unavailable_reason is None,
            "reason": unavailable_reason,
            "interfaces": interfaces,
            "source": "configured_host_status_file" if unavailable_reason is None else "unavailable",
        },
        "modules": module_rows,
    }


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
