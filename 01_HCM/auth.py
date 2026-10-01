from __future__ import annotations
import hashlib
import json
import secrets
import time
from typing import Any
from fastapi import Header, HTTPException
from . import db
from .settings import settings

# First pass local auth. Replace challenge verification with platform passkey/WebAuthn once RP ID is finalized.
_sessions: dict[str, tuple[str,str,float]] = {}


def create_session(user: str, role: str='ADMIN', ttl_s: int=3600) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = (user, role, time.time()+ttl_s)
    return token

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

async def create_persistent_session(user: str, role: str, ttl_s: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_sessions(username,token_hash,role,expires_at)
            VALUES($1,$2,$3,now() + ($4::text || ' seconds')::interval)
            """,
            user,
            _token_hash(token),
            role,
            ttl_s or settings.auth_session_ttl_s,
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
            VALUES($1,$2,now() + ($3::text || ' seconds')::interval)
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
