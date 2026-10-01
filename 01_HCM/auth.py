from __future__ import annotations
import secrets, time
from fastapi import Header, HTTPException

# First pass local auth. Replace challenge verification with platform passkey/WebAuthn once RP ID is finalized.
_sessions: dict[str, tuple[str,str,float]] = {}


def create_session(user: str, role: str='ADMIN', ttl_s: int=3600) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = (user, role, time.time()+ttl_s)
    return token

async def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'missing bearer token')
    token = authorization[7:]
    sess = _sessions.get(token)
    if not sess or sess[2] < time.time():
        raise HTTPException(401, 'invalid/expired token')
    return {'user': sess[0], 'role': sess[1]}
