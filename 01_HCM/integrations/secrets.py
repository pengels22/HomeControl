"""Encrypted integration credentials. Plaintext is never persisted or returned."""
import base64, hashlib, json, os
from cryptography.fernet import Fernet, InvalidToken
from ..settings import settings
from .. import db

KINDS={'api_key','username_password','oauth_access_token','oauth_refresh_token','client_secret','webhook_secret'}

def _fernet():
    raw=os.getenv('HCM_INTEGRATION_SECRET_KEY','').encode()
    if not raw and settings.integration_secret_key_file:
        try: raw=settings.integration_secret_key_file.read_bytes().strip()
        except OSError: raw=b''
    if not raw: raise RuntimeError('Integration secret key is not configured')
    try: return Fernet(raw)
    except Exception as exc: raise RuntimeError('Integration secret key is invalid') from exc

async def put(provider_id, kind, value, *, metadata=None):
    if kind not in KINDS or not value: raise ValueError('Credential value is required')
    blob=json.dumps(value, separators=(',',':')).encode() if isinstance(value,(dict,list)) else str(value).encode()
    token=_fernet().encrypt(blob)
    async with db.acquire() as conn:
        row=await conn.fetchrow('''INSERT INTO integration_credentials(provider_id,kind,ciphertext,metadata)
            VALUES($1,$2,$3,$4::jsonb) RETURNING credential_ref''',provider_id,kind,token,json.dumps(metadata or {}))
    return str(row['credential_ref'])

async def get(ref):
    async with db.acquire() as conn: row=await conn.fetchrow('SELECT ciphertext FROM integration_credentials WHERE credential_ref=$1 AND revoked_at IS NULL',ref)
    if not row: raise LookupError('Credential unavailable')
    try:
        value=_fernet().decrypt(bytes(row['ciphertext'])).decode()
        try: return json.loads(value)
        except json.JSONDecodeError: return value
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc: raise RuntimeError('Credential unavailable') from exc

async def revoke(ref):
    async with db.acquire() as conn: await conn.execute('UPDATE integration_credentials SET revoked_at=now(),updated_at=now() WHERE credential_ref=$1',ref)
