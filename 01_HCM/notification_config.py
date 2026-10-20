"""Persistent notification destinations and speech backend configuration.

This module owns configuration and deterministic mock delivery only.  It never
connects to a push or speech provider unless a future adapter explicitly claims
the configured backend type.
"""
from __future__ import annotations
import json
from uuid import UUID
from . import db

SAFE_TYPES = {'mock','companion','email','provider'}

def _uuid(value):
    try: return UUID(str(value))
    except (ValueError, TypeError, AttributeError): raise ValueError('Invalid immutable ID') from None

def _public(row):
    if not row: return None
    result=dict(row)
    for key in ('config','languages','voices'):
        if isinstance(result.get(key),str): result[key]=json.loads(result[key])
    result.pop('credential_ref',None)
    return result

async def list_destinations():
    async with db.acquire() as conn: rows=await conn.fetch('SELECT * FROM notification_destinations ORDER BY name,destination_id')
    return [_public(row) for row in rows]

async def get_destination(destination_id):
    async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM notification_destinations WHERE destination_id=$1',_uuid(destination_id))
    if not row: raise LookupError('Notification destination not found')
    return _public(row)

async def create_destination(name,destination_type,config=None,*,enabled=True,configured=False,credential_ref=None):
    if destination_type not in SAFE_TYPES: raise ValueError('Unsupported notification destination type')
    status='configured' if configured else 'unconfigured'
    async with db.acquire() as conn:
        row=await conn.fetchrow('''INSERT INTO notification_destinations(name,destination_type,enabled,configured,status,config,credential_ref)
            VALUES($1,$2,$3,$4,$5,$6::jsonb,$7) RETURNING *''',str(name).strip(),destination_type,bool(enabled),bool(configured),status,json.dumps(config or {}),credential_ref)
    return _public(row)

async def update_destination(destination_id,body):
    current=await get_destination(destination_id); values={**current,**body}; configured=bool(values.get('configured',current['configured']))
    status=values.get('status') or ('configured' if configured else 'unconfigured')
    async with db.acquire() as conn:
        row=await conn.fetchrow('''UPDATE notification_destinations SET name=$2,destination_type=$3,enabled=$4,configured=$5,status=$6,config=$7::jsonb,updated_at=now() WHERE destination_id=$1 RETURNING *''',_uuid(destination_id),str(values['name']),values['destination_type'],bool(values['enabled']),configured,status,json.dumps(values.get('config') or {}))
    return _public(row)

async def delete_destination(destination_id):
    did=_uuid(destination_id)
    async with db.acquire() as conn:
        if await conn.fetchval('SELECT 1 FROM notification_source_mappings WHERE destination_id=$1',did): raise ValueError('Notification destination is referenced')
        result=await conn.execute('DELETE FROM notification_destinations WHERE destination_id=$1',did)
    return result.endswith('1')

async def list_backends():
    async with db.acquire() as conn: rows=await conn.fetch('SELECT * FROM speech_backends ORDER BY name,backend_id')
    return [_public(row) for row in rows]

async def get_backend(backend_id):
    async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM speech_backends WHERE backend_id=$1',_uuid(backend_id))
    if not row: raise LookupError('Speech backend not found')
    return _public(row)

async def create_backend(name,backend_type,config=None,*,enabled=True,configured=False,languages=None,voices=None,credential_ref=None):
    if backend_type not in SAFE_TYPES: raise ValueError('Unsupported speech backend type')
    status='configured' if configured else 'unconfigured'
    async with db.acquire() as conn:
        row=await conn.fetchrow('''INSERT INTO speech_backends(name,backend_type,enabled,configured,status,config,languages,voices,credential_ref)
            VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9) RETURNING *''',str(name).strip(),backend_type,bool(enabled),bool(configured),status,json.dumps(config or {}),json.dumps(languages or []),json.dumps(voices or []),credential_ref)
    return _public(row)

async def update_backend(backend_id,body):
    current=await get_backend(backend_id); values={**current,**body}; configured=bool(values.get('configured',current['configured']))
    status=values.get('status') or ('configured' if configured else 'unconfigured')
    async with db.acquire() as conn:
        row=await conn.fetchrow('''UPDATE speech_backends SET name=$2,backend_type=$3,enabled=$4,configured=$5,status=$6,config=$7::jsonb,languages=$8::jsonb,voices=$9::jsonb,updated_at=now() WHERE backend_id=$1 RETURNING *''',_uuid(backend_id),str(values['name']),values['backend_type'],bool(values['enabled']),configured,status,json.dumps(values.get('config') or {}),json.dumps(values.get('languages') or []),json.dumps(values.get('voices') or []))
    return _public(row)

async def delete_backend(backend_id):
    bid=_uuid(backend_id)
    async with db.acquire() as conn:
        if await conn.fetchval('SELECT 1 FROM speech_source_mappings WHERE backend_id=$1',bid): raise ValueError('Speech backend is referenced')
        result=await conn.execute('DELETE FROM speech_backends WHERE backend_id=$1',bid)
    return result.endswith('1')

async def set_notification_mapping(source_service,destination_id):
    await get_destination(destination_id)
    async with db.acquire() as conn: await conn.execute('''INSERT INTO notification_source_mappings(source_service,destination_id) VALUES($1,$2) ON CONFLICT(source_service) DO UPDATE SET destination_id=EXCLUDED.destination_id,updated_at=now()''',source_service,_uuid(destination_id))
    return {'source_service':source_service,'destination_id':str(destination_id)}

async def set_speech_mapping(source_entity,backend_id):
    await get_backend(backend_id)
    async with db.acquire() as conn: await conn.execute('''INSERT INTO speech_source_mappings(source_entity,backend_id) VALUES($1,$2) ON CONFLICT(source_entity) DO UPDATE SET backend_id=EXCLUDED.backend_id,updated_at=now()''',source_entity,_uuid(backend_id))
    return {'source_entity':source_entity,'backend_id':str(backend_id)}

async def resolve_notification(source_service,destination_id=None):
    async with db.acquire() as conn:
        row=await conn.fetchrow('SELECT * FROM notification_destinations WHERE destination_id=$1' if destination_id else 'SELECT d.* FROM notification_source_mappings m JOIN notification_destinations d ON d.destination_id=m.destination_id WHERE m.source_service=$1',_uuid(destination_id) if destination_id else source_service)
    return _public(row)

async def resolve_backend(source_entity=None,backend_id=None):
    async with db.acquire() as conn:
        if backend_id: row=await conn.fetchrow('SELECT * FROM speech_backends WHERE backend_id=$1',_uuid(backend_id))
        elif source_entity: row=await conn.fetchrow('SELECT b.* FROM speech_source_mappings m JOIN speech_backends b ON b.backend_id=m.backend_id WHERE m.source_entity=$1',source_entity)
        else: row=await conn.fetchrow('SELECT * FROM speech_backends WHERE enabled ORDER BY created_at LIMIT 1')
    return _public(row)
