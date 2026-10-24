"""Provider-neutral OAuth state and token lifecycle primitives."""
import hashlib, secrets
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from .. import db
from .secrets import put

@dataclass(frozen=True)
class OAuthMetadata:
    authorization_endpoint: str
    token_endpoint: str
    scopes: tuple[str,...]=()
    token_auth_style: str='client_secret_post'
    extra_authorization: dict|None=None
    extra_token: dict|None=None
    revoke_endpoint: str|None=None

@dataclass(frozen=True)
class NormalizedToken:
    access_token: str
    refresh_token: str|None
    expires_in: int|None
    expires_at: float|None
    token_type: str='Bearer'
    scopes: tuple[str,...]=()

def normalize_token(payload):
    if not isinstance(payload,dict) or not payload.get('access_token'): raise ValueError('OAuth token response invalid')
    expires=payload.get('expires_in'); expires=int(expires) if expires is not None else None
    return NormalizedToken(str(payload['access_token']),payload.get('refresh_token'),expires,__import__('time').time()+expires if expires else None,str(payload.get('token_type','Bearer')),tuple(str(payload.get('scope','')).split()))

class OAuthHTTPClient:
    def __init__(self,request): self.request=request
    async def exchange(self,metadata,code,client_id,client_secret,redirect_uri):
        data={'grant_type':'authorization_code','code':code,'redirect_uri':redirect_uri,**(metadata.extra_token or {})}
        data['client_id']=client_id
        if metadata.token_auth_style=='client_secret_post': data['client_secret']=client_secret
        payload=await self.request(metadata.token_endpoint,data,metadata.token_auth_style)
        return normalize_token(payload)
    async def refresh(self,metadata,refresh_token,client_id,client_secret):
        data={'grant_type':'refresh_token','refresh_token':refresh_token,'client_id':client_id,**(metadata.extra_token or {})}
        if metadata.token_auth_style=='client_secret_post': data['client_secret']=client_secret
        return normalize_token(await self.request(metadata.token_endpoint,data,metadata.token_auth_style))

class RefreshScheduler:
    def __init__(self): self.tasks={}
    def schedule(self,key,runner,delay):
        self.cancel(key); self.tasks[key]=asyncio.create_task(self._run(key,runner,delay))
    async def _run(self,key,runner,delay):
        try:
            await asyncio.sleep(max(1,delay)); await runner()
        except asyncio.CancelledError: raise
        except Exception: pass
    def cancel(self,key):
        task=self.tasks.pop(key,None)
        if task: task.cancel()
    async def stop(self):
        for key in list(self.tasks): self.cancel(key)

refresh_scheduler=RefreshScheduler()

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

async def associate_access_credential(instance_id,credential_ref):
    async with db.acquire() as conn:
        await conn.execute("UPDATE integration_instances SET credential_ref=$2,configured=true,status='connected',last_success=now(),updated_at=now() WHERE instance_id=$1",instance_id,credential_ref)
