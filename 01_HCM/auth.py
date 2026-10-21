from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import time
import asyncio
import base64
import hashlib as _hashlib
from typing import Any
from fastapi import Header, HTTPException
from importlib import import_module
from . import db
from .settings import settings

# First pass local auth. Replace challenge verification with platform passkey/WebAuthn once RP ID is finalized.
_sessions: dict[str, tuple[str,str,float]] = {}
global_config = import_module('08_servises.common.global_config')
module_infra = import_module('08_servises.common.module_infra')
PASSWORD_ITERATIONS = int(global_config.load_global_config('HCM').Auth_Password_PBKDF2_Iterations)
SUPPORTED_ROLES = {"ADMIN", "READONLY"}
TOUCHSCREEN_PERMISSIONS = {"VIEWER", "CONTROL", "ADMIN"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
PIN_RE = re.compile(r"^[0-9]{6}$")


def create_session(user: str, role: str='ADMIN', ttl_s: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = (user, role, time.time() + (ttl_s or settings.auth_session_ttl_s))
    return token

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"

def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        scheme, iterations_raw, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
    return hmac.compare_digest(digest.hex(), expected)


def _pin_secret() -> bytes:
    path = settings.touchscreen_pin_lookup_secret_file
    if not path:
        raise RuntimeError("touchscreen PIN lookup secret is not configured")
    try:
        secret = path.read_bytes().strip()
    except OSError as exc:
        raise RuntimeError("touchscreen PIN lookup secret is unavailable") from exc
    if len(secret) < 32:
        raise RuntimeError("touchscreen PIN lookup secret is too short")
    return secret


def _validate_pin(pin: str) -> str:
    value = str(pin or "")
    if not PIN_RE.fullmatch(value):
        raise HTTPException(400, "PIN must contain exactly six digits")
    return value


def touchscreen_pin_lookup(pin: str) -> str:
    return hmac.new(_pin_secret(), _validate_pin(pin).encode(), hashlib.sha256).hexdigest()


def hash_touchscreen_pin(pin: str) -> str:
    value = _validate_pin(pin).encode()
    salt = secrets.token_bytes(16)
    digest = _hashlib.scrypt(value, salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$%s$%s" % (base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())


def verify_touchscreen_pin(pin: str, encoded: str | None) -> bool:
    try:
        scheme, n, r, p, salt_raw, expected_raw = str(encoded or "").split("$", 5)
        if scheme != "scrypt":
            return False
        digest = _hashlib.scrypt(_validate_pin(pin).encode(), salt=base64.urlsafe_b64decode(salt_raw), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest, base64.urlsafe_b64decode(expected_raw))
    except (ValueError, TypeError, MemoryError):
        return False


def _validate_touchscreen_permission(permission: str) -> str:
    value = str(permission or "").upper()
    if value not in TOUCHSCREEN_PERMISSIONS:
        raise HTTPException(400, "invalid touchscreen permission")
    return value

def _validate_username(username: str) -> str:
    clean = str(username or "").strip()
    if not USERNAME_RE.fullmatch(clean):
        raise HTTPException(400, "invalid username")
    return clean

def _validate_role(role: str) -> str:
    clean = str(role or "").upper()
    if clean not in SUPPORTED_ROLES:
        raise HTTPException(400, "invalid role")
    return clean

def _validate_password(password: str) -> None:
    if len(password or "") < 10:
        raise HTTPException(400, "password must be at least 10 characters")

async def create_persistent_session(user: str, role: str, ttl_s: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_sessions(username,token_hash,role,expires_at)
            VALUES($1,$2,$3,now() + ($4::integer * interval '1 second'))
            """,
            user,
            _token_hash(token),
            role,
            ttl_s or settings.auth_session_ttl_s,
        )
    return token

async def list_users() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT username, role, enabled, created_at, touchscreen_pin_enabled, touchscreen_permission
            FROM users
            ORDER BY username
            """
        )
    return [
        {
            "username": row["username"],
            "role": row["role"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "touchscreen_pin_enabled": bool(row.get("touchscreen_pin_enabled", False)),
            "touchscreen_permission": row.get("touchscreen_permission", "VIEWER"),
        }
        for row in rows
    ]


async def build_user_snapshot(device_id: str) -> dict[str, Any]:
    """Build the only user material permitted to cross an authenticated module link."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT username, role, password_hash, enabled
            FROM users
            ORDER BY username
            """
        )
    users = [{
        "username": str(row["username"]),
        "role": str(row["role"]).upper(),
        "enabled": bool(row["enabled"]),
        "verifier": str(row["password_hash"] or ""),
    } for row in rows]
    if any(not item["verifier"] for item in users):
        raise RuntimeError("user directory contains an account without a password verifier")
    target = str(device_id).lower()
    body = {"target_device_id": target, "issued_at": time.time_ns(), "users": users}
    revision = module_infra.stable_revision(body)
    signed_body = {**body, "revision": revision}
    return {**signed_body, "checksum": module_infra.stable_revision(signed_body)}


async def enroll_touchscreen_pin(username: str, pin: str, permission: str = "VIEWER") -> dict[str, Any]:
    username = _validate_username(username)
    pin = _validate_pin(pin)
    permission = _validate_touchscreen_permission(permission)
    lookup = touchscreen_pin_lookup(pin)
    verifier = hash_touchscreen_pin(pin)
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT id, username, enabled FROM users WHERE username=$1 FOR UPDATE", username)
        if not row or not row["enabled"]:
            raise HTTPException(404, "user not found")
        duplicate = await conn.fetchrow(
            "SELECT username FROM users WHERE touchscreen_pin_lookup=$1 AND touchscreen_pin_enabled=true AND username<>$2",
            lookup, username,
        )
        if duplicate:
            raise HTTPException(409, "PIN is already enrolled")
        await conn.execute(
            """UPDATE users SET touchscreen_pin_hash=$2, touchscreen_pin_lookup=$3,
               touchscreen_pin_enabled=true, touchscreen_permission=$4,
               touchscreen_pin_changed_at=now() WHERE username=$1""",
            username, verifier, lookup, permission,
        )
        await conn.execute("UPDATE touchscreen_sessions SET revoked_at=now(), revoke_reason='pin_reset' WHERE user_id=$1 AND revoked_at IS NULL", row["id"])
    return {"ok": True, "username": username, "touchscreen_pin_enabled": True, "touchscreen_permission": permission, "sessions_revoked": True}


async def disable_touchscreen_pin(username: str) -> dict[str, Any]:
    username = _validate_username(username)
    async with db.acquire() as conn:
        row = await conn.fetchrow("UPDATE users SET touchscreen_pin_enabled=false, touchscreen_pin_lookup=NULL, touchscreen_pin_hash=NULL, touchscreen_pin_changed_at=now() WHERE username=$1 RETURNING id, username", username)
        if not row:
            raise HTTPException(404, "user not found")
        await conn.execute("UPDATE touchscreen_sessions SET revoked_at=now(), revoke_reason='pin_disabled' WHERE user_id=$1 AND revoked_at IS NULL", row["id"])
    return {"ok": True, "username": username, "touchscreen_pin_enabled": False, "sessions_revoked": True}


async def set_touchscreen_permission(username: str, permission: str) -> dict[str, Any]:
    username = _validate_username(username)
    permission = _validate_touchscreen_permission(permission)
    async with db.acquire() as conn:
        row = await conn.fetchrow("UPDATE users SET touchscreen_permission=$2 WHERE username=$1 AND enabled=true RETURNING id, username, touchscreen_pin_enabled", username, permission)
        if not row:
            raise HTTPException(404, "user not found")
        await conn.execute("UPDATE touchscreen_sessions SET revoked_at=now(), revoke_reason='permission_changed' WHERE user_id=$1 AND revoked_at IS NULL", row["id"])
    return {"ok": True, "username": username, "touchscreen_permission": permission, "sessions_revoked": True}


async def revoke_touchscreen_sessions(username: str) -> dict[str, Any]:
    username = _validate_username(username)
    async with db.acquire() as conn:
        result = await conn.execute("UPDATE touchscreen_sessions SET revoked_at=now(), revoke_reason='admin_revoked' WHERE user_id=(SELECT id FROM users WHERE username=$1) AND revoked_at IS NULL", username)
    return {"ok": True, "username": username, "sessions_revoked": True, "updated": result}


async def authenticate_touchscreen_device(device_id: str, device_token: str) -> dict[str, Any]:
    """Validate a provisioned touchscreen identity without trusting its headers."""
    if not device_id or not device_token:
        raise HTTPException(401, "touchscreen authentication failed")
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, device_id, token_hash, enabled, revoked_at, permitted_module_ids
               FROM touchscreen_devices WHERE device_id=$1""", str(device_id)
        )
    if not row or not row["enabled"] or row["revoked_at"]:
        raise HTTPException(401, "touchscreen authentication failed")
    if not hmac.compare_digest(str(row["token_hash"]), _token_hash(device_token)):
        raise HTTPException(401, "touchscreen authentication failed")
    return dict(row)


async def _rate_check(conn, scopes: list[str]) -> None:
    blocked = await conn.fetchrow(
        "SELECT scope FROM touchscreen_rate_limits WHERE scope=ANY($1::text[]) AND next_allowed_at > now() LIMIT 1",
        scopes,
    )
    if blocked:
        raise HTTPException(429, "touchscreen authentication temporarily unavailable")


async def _clear_rate_limits(conn, scopes: list[str]) -> None:
    for scope in scopes:
        await conn.execute("DELETE FROM touchscreen_rate_limits WHERE scope=$1", scope)


async def _record_rate_failure(conn, scopes: list[str]) -> None:
    for scope in scopes:
        row = await conn.fetchrow("SELECT failed_attempts FROM touchscreen_rate_limits WHERE scope=$1 FOR UPDATE", scope)
        attempts = int(row["failed_attempts"] if row else 0) + 1
        delay = min(settings.touchscreen_rate_limit_max_s, settings.touchscreen_rate_limit_base_s * (2 ** min(attempts - 1, 8)))
        await conn.execute(
            """INSERT INTO touchscreen_rate_limits(scope, failed_attempts, next_allowed_at, last_failed_at, updated_at)
               VALUES($1,$2,now() + ($3::integer * interval '1 second'),now(),now())
               ON CONFLICT(scope) DO UPDATE SET failed_attempts=$2,
               next_allowed_at=now() + ($3::integer * interval '1 second'), last_failed_at=now(), updated_at=now()""",
            scope, attempts, delay,
        )


async def _normal_login_rate_check(conn, username: str) -> None:
    row = await conn.fetchrow(
        "SELECT failed_attempts, next_allowed_at FROM auth_login_rate_limits WHERE scope=$1",
        username,
    )
    if row and row["next_allowed_at"] is not None:
        # PostgreSQL performs the timestamp comparison; a non-null value here
        # is only written for an active five-minute lockout.
        active = await conn.fetchrow(
            "SELECT 1 FROM auth_login_rate_limits WHERE scope=$1 AND next_allowed_at > now()",
            username,
        )
        if active:
            raise HTTPException(429, "login temporarily unavailable")
        await conn.execute("DELETE FROM auth_login_rate_limits WHERE scope=$1", username)


async def _normal_login_failure(conn, username: str) -> None:
    row = await conn.fetchrow(
        "SELECT failed_attempts FROM auth_login_rate_limits WHERE scope=$1 FOR UPDATE",
        username,
    )
    attempts = int(row["failed_attempts"] if row else 0) + 1
    await conn.execute(
        """INSERT INTO auth_login_rate_limits(scope, failed_attempts, next_allowed_at, last_failed_at, updated_at)
           VALUES($1,$2,CASE WHEN $2 >= 5 THEN now() + interval '5 minutes' ELSE NULL END,now(),now())
           ON CONFLICT(scope) DO UPDATE SET failed_attempts=$2,
           next_allowed_at=CASE WHEN $2 >= 5 THEN now() + interval '5 minutes' ELSE NULL END,
           last_failed_at=now(), updated_at=now()""",
        username, attempts,
    )


async def _clear_normal_login_rate(conn, username: str) -> None:
    await conn.execute("DELETE FROM auth_login_rate_limits WHERE scope=$1", username)


async def unlock_touchscreen(pin: str, device_id: str, device_token: str) -> dict[str, Any]:
    device = await authenticate_touchscreen_device(device_id, device_token)
    scopes = ["global", f"device:{device['device_id']}"]
    async with db.acquire() as conn:
        await _rate_check(conn, scopes)
        lookup = touchscreen_pin_lookup(pin)
        row = await conn.fetchrow(
            """SELECT id, username, touchscreen_pin_hash, touchscreen_pin_enabled,
                      touchscreen_permission, enabled
               FROM users WHERE touchscreen_pin_lookup=$1""", lookup
        )
        if not row or not row["enabled"] or not row["touchscreen_pin_enabled"] or not verify_touchscreen_pin(pin, row["touchscreen_pin_hash"]):
            await _record_rate_failure(conn, scopes)
            raise HTTPException(401, "touchscreen authentication failed")
        await _clear_rate_limits(conn, scopes)
        token = secrets.token_urlsafe(32)
        await conn.execute(
            """INSERT INTO touchscreen_sessions(user_id,device_id,token_hash,permission,idle_expires_at,absolute_expires_at)
               VALUES($1,$2,$3,$4,now() + ($5::integer * interval '1 second'),now() + ($6::integer * interval '1 second'))""",
            row["id"], device["id"], _token_hash(token), row["touchscreen_permission"],
            settings.touchscreen_idle_timeout_s, settings.touchscreen_absolute_timeout_s,
        )
    return {
        "ok": True,
        "session_token": token,
        "user": row["username"],
        "permission": row["touchscreen_permission"],
        "idle_timeout_seconds": settings.touchscreen_idle_timeout_s,
        "absolute_timeout_seconds": settings.touchscreen_absolute_timeout_s,
    }


async def require_touchscreen_session(session_token: str, device_id: str, *, refresh: bool = False) -> dict[str, Any]:
    if not session_token or not device_id:
        raise HTTPException(401, "touchscreen session required")
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT s.id, s.permission, s.user_id, u.username, u.enabled AS user_enabled,
                      u.touchscreen_pin_enabled, d.device_id, d.enabled AS device_enabled,
                      s.idle_expires_at, s.absolute_expires_at
               FROM touchscreen_sessions s
               JOIN users u ON u.id=s.user_id
               JOIN touchscreen_devices d ON d.id=s.device_id
               WHERE s.token_hash=$1 AND d.device_id=$2 AND s.revoked_at IS NULL
                 AND s.idle_expires_at > now() AND s.absolute_expires_at > now()""",
            _token_hash(session_token), str(device_id),
        )
        if not row or not row["user_enabled"] or not row["touchscreen_pin_enabled"] or not row["device_enabled"]:
            raise HTTPException(401, "touchscreen session expired or revoked")
        if refresh:
            await conn.execute(
                "UPDATE touchscreen_sessions SET last_activity_at=now(), idle_expires_at=now() + ($2::integer * interval '1 second') WHERE id=$1",
                row["id"], settings.touchscreen_idle_timeout_s,
            )
    return {"user": row["username"], "permission": row["permission"], "device_id": row["device_id"], "session_id": row["id"]}


async def touchscreen_device_permits_logical(device_id: str, logical_name: str) -> bool:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT d.permitted_module_ids, m.hostname, m.device_id AS module_device_id
               FROM touchscreen_devices d
               JOIN device_bindings b ON b.enabled=true
               JOIN logical_devices ld ON ld.id=b.logical_device_id AND ld.enabled=true
               JOIN modules m ON m.id=b.module_id
               WHERE d.device_id=$1 AND ld.logical_name=$2
               LIMIT 1""",
            str(device_id), logical_name,
        )
    if not row:
        return False
    permitted = row["permitted_module_ids"] or []
    return str(row["hostname"]) in permitted or str(row["module_device_id"]) in permitted


async def revoke_touchscreen_session(session_token: str, device_id: str) -> dict[str, Any]:
    async with db.acquire() as conn:
        result = await conn.execute(
            """UPDATE touchscreen_sessions SET revoked_at=now(), revoke_reason='manual_logout'
               WHERE token_hash=$1 AND device_id=(SELECT id FROM touchscreen_devices WHERE device_id=$2)
                 AND revoked_at IS NULL""",
            _token_hash(session_token), str(device_id),
        )
    return {"ok": True, "revoked": result}


async def _sync_user_directory() -> list[dict[str, Any]]:
    """Push a snapshot over each existing authenticated module control session."""
    async with db.acquire() as conn:
        modules = await conn.fetch("SELECT hostname, device_id FROM modules WHERE device_id IS NOT NULL")
    snapshot_tasks = []
    for row in modules:
        snapshot_tasks.append(_sync_user_directory_module(str(row["hostname"]), str(row["device_id"])))
    return await asyncio.gather(*snapshot_tasks) if snapshot_tasks else []


async def _sync_user_directory_module(hostname: str, device_id: str) -> dict[str, Any]:
    try:
        snapshot = await build_user_snapshot(device_id)
        from .registry import registry
        ack = await registry.config_by_hostname(hostname, {"user_snapshot": snapshot}, timeout=5.0)
        return {"hostname": hostname, "device_id": device_id, "status": "synchronized" if ack.get("ok") else "rejected"}
    except Exception as exc:
        return {"hostname": hostname, "device_id": device_id, "status": "pending", "reason": str(exc)}

async def create_user(username: str, password: str, role: str) -> dict[str, Any]:
    username = _validate_username(username)
    role = _validate_role(role)
    _validate_password(password)
    async with db.acquire() as conn:
        existing = await conn.fetchrow("SELECT username FROM users WHERE username=$1", username)
        if existing:
            raise HTTPException(409, "user already exists")
        await conn.execute(
            """
            INSERT INTO users(username, role, password_hash, enabled)
            VALUES($1,$2,$3,true)
            """,
            username,
            role,
            hash_password(password),
        )
    result = {
        "ok": True,
        "username": username,
        "role": role,
        "enabled": True,
        "created_at": None,
    }
    return result


async def _safe_sync_user_directory() -> list[dict[str, Any]]:
    try:
        return await _sync_user_directory()
    except Exception as exc:
        return [{"status": "pending", "reason": str(exc)}]

async def update_user_role(username: str, role: str) -> dict[str, Any]:
    username = _validate_username(username)
    role = _validate_role(role)
    async with db.acquire() as conn:
        tx_factory = getattr(conn, "transaction", None)
        if tx_factory is None:
            row = await _update_user_role_locked(conn, username, role)
        else:
            async with tx_factory():
                row = await _update_user_role_locked(conn, username, role)
    row["synchronization"] = await _safe_sync_user_directory()
    return row

async def _update_user_role_locked(conn, username: str, role: str) -> dict[str, Any]:
    current = await conn.fetchrow("SELECT username, role, enabled FROM users WHERE username=$1 FOR UPDATE", username)
    if not current or not current["enabled"]:
        raise HTTPException(404, "user not found")
    if current["role"] == "ADMIN" and role != "ADMIN":
        admin_count = await conn.fetchval("SELECT count(*) FROM users WHERE role='ADMIN' AND enabled=true")
        if int(admin_count or 0) <= 1:
            raise HTTPException(409, "cannot demote final administrator")
    row = await conn.fetchrow(
        """
        UPDATE users
        SET role=$2
        WHERE username=$1
        RETURNING username, role, enabled, created_at
        """,
        username,
        role,
    )
    await conn.execute("UPDATE user_sessions SET revoked_at=now() WHERE username=$1 AND revoked_at IS NULL", username)
    result = {
        "ok": True,
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "sessions_revoked": True,
    }
    result["synchronization"] = await _safe_sync_user_directory()
    return result

async def reset_user_password(username: str, password: str) -> dict[str, Any]:
    username = _validate_username(username)
    _validate_password(password)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET password_hash=$2
            WHERE username=$1 AND enabled=true
            RETURNING username, role, enabled, created_at
            """,
            username,
            hash_password(password),
        )
        if not row:
            raise HTTPException(404, "user not found")
        await conn.execute("UPDATE user_sessions SET revoked_at=now() WHERE username=$1 AND revoked_at IS NULL", username)
        await _clear_normal_login_rate(conn, username)
    result = {
        "ok": True,
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "sessions_revoked": True,
    }
    result["synchronization"] = await _safe_sync_user_directory()
    return result

async def change_own_password(username: str, current_password: str, new_password: str) -> dict[str, Any]:
    username = _validate_username(username)
    _validate_password(new_password)
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT username, password_hash FROM users WHERE username=$1 AND enabled=true", username)
        if not row or not verify_password(current_password, row["password_hash"]):
            raise HTTPException(401, "invalid current password")
        await conn.execute("UPDATE users SET password_hash=$2 WHERE username=$1", username, hash_password(new_password))
        await conn.execute("UPDATE user_sessions SET revoked_at=now() WHERE username=$1 AND revoked_at IS NULL", username)
        await _clear_normal_login_rate(conn, username)
    return {"ok": True, "username": username, "sessions_revoked": True, "synchronization": await _safe_sync_user_directory()}

async def login_password(username: str, password: str) -> str:
    username = _validate_username(username)
    async with db.acquire() as conn:
        await _normal_login_rate_check(conn, username)
        row = await conn.fetchrow(
            "SELECT username, role, password_hash FROM users WHERE username=$1 AND enabled=true",
            username,
        )
        if not row or not verify_password(password, row["password_hash"]):
            await _normal_login_failure(conn, username)
            raise HTTPException(401, "invalid username/password")
        await _clear_normal_login_rate(conn, username)
        token = secrets.token_urlsafe(32)
        await conn.execute(
            """INSERT INTO user_sessions(username,token_hash,role,expires_at)
               VALUES($1,$2,$3,now() + ($4::integer * interval '1 second'))""",
            row["username"], _token_hash(token), row["role"], settings.auth_session_ttl_s,
        )
        return token

async def create_login_challenge(username: str) -> dict[str, Any]:
    async with db.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT username, role, passkey_credential FROM users WHERE username=$1 AND enabled=true",
            username,
        )
        if not user or not user["passkey_credential"]:
            raise HTTPException(404, "passkey user not found")
        challenge = secrets.token_urlsafe(32)
        await conn.execute(
            """
            INSERT INTO auth_challenges(username,challenge,expires_at)
            VALUES($1,$2,now() + ($3::integer * interval '1 second'))
            """,
            username,
            challenge,
            settings.auth_challenge_ttl_s,
        )
    return {"rp_id": settings.auth_rp_id, "username": username, "challenge": challenge}

def verify_passkey_assertion(passkey_credential: Any, challenge: str, assertion: dict[str, Any]) -> bool:
    credential = passkey_credential
    if isinstance(credential, str):
        credential = json.loads(credential)
    if isinstance(credential, dict) and credential.get("type") == "insecure-dev" and settings.dev_mode:
        return assertion.get("challenge") == challenge and assertion.get("response") == credential.get("response")
    raise NotImplementedError("production WebAuthn assertion verification adapter is not configured")

async def verify_login_challenge(username: str, challenge: str, assertion: dict[str, Any]) -> str:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.id, u.username, u.role, u.passkey_credential
            FROM auth_challenges c
            JOIN users u ON u.username=c.username
            WHERE c.username=$1
              AND c.challenge=$2
              AND c.consumed_at IS NULL
              AND c.expires_at > now()
              AND u.enabled=true
            """,
            username,
            challenge,
        )
        if not row:
            raise HTTPException(401, "invalid/expired challenge")
        try:
            ok = verify_passkey_assertion(row["passkey_credential"], challenge, assertion)
        except NotImplementedError as exc:
            raise HTTPException(501, str(exc)) from exc
        if not ok:
            raise HTTPException(401, "invalid assertion")
        await conn.execute("UPDATE auth_challenges SET consumed_at=now() WHERE id=$1", row["id"])
    return await create_persistent_session(row["username"], row["role"])

async def create_pairing_key(
    label: str,
    target_type: str,
    created_by: str,
    ttl_minutes: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pairing_key = secrets.token_urlsafe(24)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pairing_keys(
                label,target_type,pairing_token_hash,created_by,expires_at,metadata
            )
            VALUES($1,$2,$3,$4,now() + ($5::integer * interval '1 minute'),$6::jsonb)
            RETURNING id, label, target_type, expires_at
            """,
            label,
            target_type,
            _token_hash(pairing_key),
            created_by,
            ttl_minutes,
            json.dumps(metadata or {}),
        )
    return {
        "id": row["id"],
        "label": row["label"],
        "target_type": row["target_type"],
        "expires_at": row["expires_at"].isoformat(),
        "pairing_key": pairing_key,
    }

async def verify_pairing_key(pairing_key: str, used_by: str | None = None) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE pairing_keys
            SET used_at=now(), used_by=$2
            WHERE pairing_token_hash=$1
              AND used_at IS NULL
              AND expires_at > now()
            RETURNING id, label, target_type, metadata
            """,
            _token_hash(pairing_key),
            used_by,
        )
    if not row:
        raise HTTPException(401, "invalid/expired pairing key")
    metadata = row["metadata"] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return {
        "ok": True,
        "id": row["id"],
        "label": row["label"],
        "target_type": row["target_type"],
        "metadata": metadata,
    }

async def list_pairing_keys() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id,label,target_type,created_by,created_at,expires_at,used_at,used_by
            FROM pairing_keys
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "target_type": r["target_type"],
            "created_by": r["created_by"],
            "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(),
            "used_at": r["used_at"].isoformat() if r["used_at"] else None,
            "used_by": r["used_by"],
        }
        for r in rows
    ]

async def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'missing bearer token')
    token = authorization[7:]
    sess = _sessions.get(token)
    if sess and settings.dev_mode and sess[2] >= time.time():
        return {'user': sess[0], 'role': sess[1]}
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.username, u.role
            FROM user_sessions s
            JOIN users u ON u.username=s.username
            WHERE s.token_hash=$1
              AND u.enabled=true
              AND s.revoked_at IS NULL
              AND s.expires_at > now()
            """,
            _token_hash(token),
        )
    if not row:
        raise HTTPException(401, 'invalid/expired token')
    return {'user': row['username'], 'role': row['role']}
