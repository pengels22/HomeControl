from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any
from fastapi import Header, HTTPException
from importlib import import_module
from . import db
from .settings import settings

# First pass local auth. Replace challenge verification with platform passkey/WebAuthn once RP ID is finalized.
_sessions: dict[str, tuple[str,str,float]] = {}
global_config = import_module('07_servises.common.global_config')
PASSWORD_ITERATIONS = int(global_config.load_global_config('HCM').Auth_Password_PBKDF2_Iterations)
SUPPORTED_ROLES = {"ADMIN", "READONLY"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


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
            SELECT username, role, enabled, created_at
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
        }
        for row in rows
    ]

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
    return {
        "ok": True,
        "username": username,
        "role": role,
        "enabled": True,
        "created_at": None,
    }

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
    return {
        "ok": True,
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "sessions_revoked": True,
    }

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
    return {
        "ok": True,
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "sessions_revoked": True,
    }

async def change_own_password(username: str, current_password: str, new_password: str) -> dict[str, Any]:
    username = _validate_username(username)
    _validate_password(new_password)
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT username, password_hash FROM users WHERE username=$1 AND enabled=true", username)
        if not row or not verify_password(current_password, row["password_hash"]):
            raise HTTPException(401, "invalid current password")
        await conn.execute("UPDATE users SET password_hash=$2 WHERE username=$1", username, hash_password(new_password))
        await conn.execute("UPDATE user_sessions SET revoked_at=now() WHERE username=$1 AND revoked_at IS NULL", username)
    return {"ok": True, "username": username, "sessions_revoked": True}

async def login_password(username: str, password: str) -> str:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username, role, password_hash FROM users WHERE username=$1 AND enabled=true",
            username,
        )
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(401, "invalid username/password")
    return await create_persistent_session(row["username"], row["role"])

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
    if sess and sess[2] >= time.time():
        return {'user': sess[0], 'role': sess[1]}
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT username, role
            FROM user_sessions
            WHERE token_hash=$1
              AND revoked_at IS NULL
              AND expires_at > now()
            """,
            _token_hash(token),
        )
    if not row:
        raise HTTPException(401, 'invalid/expired token')
    return {'user': row['username'], 'role': row['role']}
