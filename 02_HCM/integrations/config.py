"""Provider configuration and credential lifecycle; response models are redacted."""
import json, re, secrets, hashlib, time
from pydantic import BaseModel, ConfigDict, Field
from .. import db
from . import secrets as secret_store

class ConfigInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config: dict = Field(default_factory=dict)
    credential_kind: str | None = None
    credential: object | None = None

def safe_error(exc): return f'{type(exc).__name__}' if not isinstance(exc,ValueError) else str(exc)[:160]

async def save(provider, payload: ConfigInput, *, actor):
    if not isinstance(payload.config,dict): raise ValueError('Configuration must be an object')
    ref=None
    if payload.credential_kind is not None:
        ref=await secret_store.put(provider.info.provider_id,payload.credential_kind,payload.credential)
    async with db.acquire() as conn:
        old_ref=await conn.fetchval('SELECT credential_ref FROM integration_providers WHERE provider_id=$1',provider.info.provider_id)
        row=await conn.fetchrow('''UPDATE integration_providers SET config=$2::jsonb,credential_ref=COALESCE($3,credential_ref),configured=true,status='starting',last_error=NULL,updated_at=now() WHERE provider_id=$1 RETURNING provider_id,credential_ref''',provider.info.provider_id,json.dumps(payload.config),ref)
        if not row: raise LookupError('Provider not found')
        if ref and old_ref and str(old_ref) != ref: await conn.execute('UPDATE integration_credentials SET revoked_at=now(),updated_at=now() WHERE credential_ref=$1',old_ref)
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,$2,'integration',$3)",actor,'integration.credential_replaced' if ref else 'integration.configured',provider.info.provider_id)
    return await inspect(provider.info.provider_id)

async def inspect(provider_id=None):
    sql='''SELECT provider_id,display_name,enabled,configured,config_schema,config,config_flow,credential_ref,status,last_success,last_error,updated_at FROM integration_providers'''
    args=[]
    if provider_id: sql+=' WHERE provider_id=$1'; args=[provider_id]
    sql+=' ORDER BY provider_id'
    async with db.acquire() as conn: rows=await conn.fetch(sql,*args)
    result=[]
    for r in rows:
        item={**dict(r),'credential_configured':bool(r['credential_ref']),'credential_ref':None}
        for key in ('config','config_schema','config_flow'):
            if isinstance(item.get(key),str): item[key]=json.loads(item[key])
        result.append(item)
    return result

async def set_enabled(provider_id,enabled,actor):
    async with db.acquire() as conn:
        row=await conn.fetchrow('UPDATE integration_providers SET enabled=$2,updated_at=now() WHERE provider_id=$1 RETURNING provider_id',provider_id,enabled)
        if not row: raise LookupError('Provider not found')
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,$2,'integration',$3)",actor,'integration.enabled' if enabled else 'integration.disabled',provider_id)

async def remove(provider_id,actor):
    async with db.acquire() as conn:
        row=await conn.fetchrow('DELETE FROM integration_providers WHERE provider_id=$1 RETURNING provider_id',provider_id)
        if not row: raise LookupError('Provider not found')
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,'integration.removed','integration',$2)",actor,provider_id)
