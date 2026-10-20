"""Instance-oriented configuration facade layered over provider definitions."""
import json
from . import secrets
from .. import db

async def list_instances():
    async with db.acquire() as conn:
        rows=await conn.fetch('''SELECT i.*,p.display_name AS provider_display_name,p.capabilities
            FROM integration_instances i JOIN integration_providers p USING(provider_id) ORDER BY i.display_name''')
    result=[]
    for r in rows:
        item=dict(r); item['credential_configured']=bool(item.get('credential_ref')); item['credential_ref']=None
        for k in ('config','config_schema','capabilities'):
            if isinstance(item.get(k),str): item[k]=json.loads(item[k])
        result.append(item)
    return result

async def create(provider_id,name,config,*,credential_kind=None,credential=None,actor='hcm'):
    ref=None
    async with db.acquire() as conn:
        provider=await conn.fetchrow('SELECT provider_id,config_schema,enabled FROM integration_providers WHERE provider_id=$1',provider_id)
        if not provider: raise LookupError('Provider not found')
        if credential is not None:
            blob=await secrets._fernet().encrypt(str(credential).encode()) if False else None
        row=await conn.fetchrow('''INSERT INTO integration_instances(provider_id,display_name,enabled,configured,config_schema,config)
            VALUES($1,$2,false,true,$3::jsonb,$4::jsonb) RETURNING instance_id''',provider_id,name,json.dumps(provider['config_schema']),json.dumps(config))
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,'integration.added','integration_instance',$2)",actor,str(row['instance_id']))
    if credential is not None:
        ref=await secrets.put(provider_id,credential_kind or 'api_key',credential)
        async with db.acquire() as conn: await conn.execute('UPDATE integration_instances SET credential_ref=$2,updated_at=now() WHERE instance_id=$1',row['instance_id'],ref)
    return str(row['instance_id'])

async def set_enabled(instance_id,enabled,actor):
    async with db.acquire() as conn:
        row=await conn.fetchrow('UPDATE integration_instances SET enabled=$2,status=$3,updated_at=now() WHERE instance_id=$1 RETURNING instance_id',(instance_id,enabled,'configuration_required' if enabled else 'disabled'))
        if not row: raise LookupError('Integration instance not found')
        if not enabled:
            await conn.execute("UPDATE logical_devices SET availability='unavailable' WHERE instance_id=$1",instance_id)
            await conn.execute("UPDATE entities SET available=false WHERE device_id IN (SELECT id FROM logical_devices WHERE instance_id=$1)",instance_id)
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,$2,'integration_instance',$3)",actor,'integration.enabled' if enabled else 'integration.disabled',str(instance_id))

async def remove(instance_id,actor):
    async with db.acquire() as conn:
        await conn.execute("UPDATE logical_devices SET availability='unavailable' WHERE instance_id=$1",instance_id)
        row=await conn.fetchrow('DELETE FROM integration_instances WHERE instance_id=$1 RETURNING instance_id,credential_ref',instance_id)
        if not row: raise LookupError('Integration instance not found')
        if row['credential_ref']: await conn.execute('UPDATE integration_credentials SET revoked_at=now() WHERE credential_ref=$1',row['credential_ref'])
        await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,'integration.removed','integration_instance',$2)",actor,str(instance_id))
