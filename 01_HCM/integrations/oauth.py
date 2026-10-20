"""Provider-neutral OAuth state and token lifecycle primitives."""
import hashlib, secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from .. import db
from .secrets import put

async def authorization_url(provider_id, authorize_endpoint, client_id, redirect_uri, scopes=(), instance_id=None):
    state=secrets.token_urlsafe(32); digest=hashlib.sha256(state.encode()).hexdigest()
    async with db.acquire() as conn:
        await conn.execute('''INSERT INTO integration_oauth_states(state_hash,provider_id,redirect_uri,expires_at)
            VALUES($1,$2,$3,now()+interval '10 minutes')''',digest,provider_id,redirect_uri)
        if instance_id: await conn.execute('UPDATE integration_oauth_states SET instance_id=$2 WHERE state_hash=$1',digest,instance_id)
    query=urlencode({'response_type':'code','client_id':client_id,'redirect_uri':redirect_uri,'scope':' '.join(scopes),'state':state})
    return f'{authorize_endpoint}?{query}'

async def consume_state(provider_id,state,redirect_uri,instance_id=None):
    digest=hashlib.sha256(str(state).encode()).hexdigest()
    async with db.acquire() as conn:
        row=await conn.fetchrow('''UPDATE integration_oauth_states SET consumed_at=now() WHERE state_hash=$1 AND provider_id=$2
            AND redirect_uri=$3 AND ($4::uuid IS NULL OR instance_id=$4) AND consumed_at IS NULL AND expires_at>now() RETURNING state_hash''',digest,provider_id,redirect_uri,instance_id)
    if not row: raise ValueError('Invalid or expired OAuth state')
    return True

async def exchange_code(provider_id, code, client_id, client_secret, redirect_uri, request):
    """Exchange through an injected HTTP function; raw responses never enter diagnostics."""
    result=await request(code=code,client_id=client_id,client_secret=client_secret,redirect_uri=redirect_uri)
    if not result.get('access_token'): raise RuntimeError('OAuth authorization failed')
    access=await put(provider_id,'oauth_access_token',result['access_token'])
    refresh=await put(provider_id,'oauth_refresh_token',result['refresh_token']) if result.get('refresh_token') else None
    return {'access_credential_ref':access,'refresh_credential_ref':refresh,'expires_in':result.get('expires_in')}

async def refresh_access_token(provider_id, refresh_token, client_id, client_secret, request):
    result=await request(refresh_token=refresh_token,client_id=client_id,client_secret=client_secret)
    if not result.get('access_token'): raise RuntimeError('OAuth refresh failed')
    return {'access_credential_ref':await put(provider_id,'oauth_access_token',result['access_token']),'expires_in':result.get('expires_in')}
