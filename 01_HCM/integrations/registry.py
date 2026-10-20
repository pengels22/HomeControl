"""Persistent provider ownership, entities and service declarations.

Devices reuse logical_devices. This module never creates module bindings or
invokes native output commands. Runtime service handlers are kept separately
from their durable, inspectable declarations.
"""
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from .. import db
from ..events import EventRecord, event_bus


_UNSET = object()


class OwnershipError(PermissionError):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value):
        raise ValueError('Invalid registry identifier')
    return value


def wire(row):
    result = dict(row)
    for key in ('capabilities','state','attributes','argument_schema','target_requirements','metadata'):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result


class Registry:
    def __init__(self, bus=event_bus):
        self.bus = bus
        from .services import Services
        self.services = Services(self)

    async def register(self, info, *, enabled=False, configured=True):
        identifier(info.provider_id)
        if not all(isinstance(k,str) and isinstance(v,bool) for k,v in info.capabilities.items()):
            raise ValueError('Capabilities must be boolean flags')
        async with db.acquire() as conn:
            async with conn.transaction():
                await conn.execute('''INSERT INTO integration_providers
                    (provider_id,display_name,version,enabled,configured,capabilities,status)
                    VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)
                    ON CONFLICT(provider_id) DO UPDATE SET display_name=EXCLUDED.display_name,
                    version=EXCLUDED.version,enabled=EXCLUDED.enabled,configured=EXCLUDED.configured,
                    capabilities=EXCLUDED.capabilities,status=EXCLUDED.status,updated_at=now()''',
                info.provider_id,info.display_name,info.version,enabled,configured,json.dumps(info.capabilities),
                'starting' if enabled and configured else 'configuration_required' if enabled else 'disabled')
                await conn.execute('''UPDATE integration_providers SET config_schema=$2::jsonb,config_flow=$3::jsonb
                    WHERE provider_id=$1''',info.provider_id,json.dumps(getattr(info,'config_schema',{})),json.dumps(getattr(info,'config_flow',{})))
                # A fresh process cannot truthfully claim old entity states are live.
                await self._unavailable(conn,info.provider_id)

    async def _unavailable(self,conn,provider_id):
        await conn.execute('UPDATE entities SET available=false WHERE provider_id=$1',provider_id)
        await conn.execute("UPDATE logical_devices SET availability='unavailable' WHERE provider_id=$1",provider_id)

    async def status(self,provider_id,status,error=None):
        async with db.acquire() as conn:
            async with conn.transaction():
                await conn.execute('''UPDATE integration_providers SET status=$2,last_error=$3,
                    last_success=CASE WHEN $2='connected' THEN now() ELSE last_success END,
                    updated_at=now() WHERE provider_id=$1''',provider_id,status,error)
                if status != 'connected':
                    await self._unavailable(conn,provider_id)

    async def inspect(self,kind,provider_id=None):
        queries = {
            'integrations': 'SELECT * FROM integration_providers',
            'devices': '''SELECT id,logical_name,display_name,room_id,device_class,enabled,
                provider_id,external_device_id,availability FROM logical_devices WHERE provider_id IS NOT NULL''',
            'entities': '''SELECT e.*,d.room_id FROM entities e JOIN logical_devices d ON d.id=e.device_id''',
            'services': 'SELECT * FROM service_definitions',
        }
        sql = queries[kind]
        if provider_id is not None:
            column='e.provider_id' if kind=='entities' else 'provider_id'
            sql += (' AND ' if kind=='devices' else ' WHERE ') + column + '=$1'
        sql += ' ORDER BY 1'
        async with db.acquire() as conn:
            return [wire(row) for row in await conn.fetch(sql,*([provider_id] if provider_id is not None else []))]

    def context(self,provider_id):
        return Context(self,identifier(provider_id))


class Context:
    def __init__(self,registry,provider_id):
        self.registry = registry
        self.provider_id = provider_id

    async def device(self,external_id,display_name,*,room_id=_UNSET,available=False):
        if not isinstance(external_id,str) or not external_id or len(external_id)>256:
            raise ValueError('External device ID required (max 256 characters)')
        # Stable configuration-facing name never depends on the presentation name.
        name=f'integration.{self.provider_id}.{sha256(external_id.encode()).hexdigest()}'
        async with db.acquire() as conn:
            row=await conn.fetchrow('''INSERT INTO logical_devices
                (logical_name,device_class,provider_id,external_device_id,display_name,room_id,availability)
                VALUES($1,'integration_device',$2,$3,$4,$5,$6)
                ON CONFLICT(provider_id,external_device_id) DO UPDATE SET
                display_name=EXCLUDED.display_name,
                room_id=CASE WHEN $7 THEN EXCLUDED.room_id ELSE logical_devices.room_id END,
                availability=EXCLUDED.availability
                RETURNING id''',name,self.provider_id,external_id,display_name,
                None if room_id is _UNSET else room_id,'available' if available else 'unavailable',room_id is not _UNSET)
        return row['id']

    async def entity(self,external_id,entity_id,device_id,display_name,*,unit=None,device_class=None):
        if not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z0-9_]+',entity_id):
            raise ValueError('Entity ID must be domain.name')
        if not isinstance(external_id,str) or not external_id or len(external_id)>256:
            raise ValueError('External entity ID required (max 256 characters)')
        async with db.acquire() as conn:
            async with conn.transaction():
                # Ownership is also enforced by the composite database foreign key.
                if not await conn.fetchval('SELECT id FROM logical_devices WHERE id=$1 AND provider_id=$2',device_id,self.provider_id):
                    raise OwnershipError('Device belongs to another provider')
                row=await conn.fetchrow('''INSERT INTO entities
                    (provider_id,external_entity_id,entity_id,domain,device_id,display_name,unit,device_class)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT(provider_id,external_entity_id) DO UPDATE SET
                    display_name=EXCLUDED.display_name,unit=EXCLUDED.unit,device_class=EXCLUDED.device_class
                    RETURNING id,entity_id,device_id''',self.provider_id,external_id,entity_id,entity_id.split('.')[0],device_id,display_name,unit,device_class)
                if row['entity_id'] != entity_id or row['device_id'] != device_id:
                    raise ValueError('Entity identity changes require explicit mapping')
        return row['id']

    async def state(self,entity_id,value,*,attributes=None,available=True,correlation_id=None):
        payload=json.dumps(value,allow_nan=False)
        attrs=json.dumps(attributes or {},allow_nan=False)
        async with db.acquire() as conn:
            async with conn.transaction():
                row=await conn.fetchrow('''UPDATE entities SET
                    last_changed=CASE WHEN last_updated IS NULL OR state IS DISTINCT FROM $3::jsonb THEN now() ELSE last_changed END,
                    state=$3::jsonb,attributes=$4::jsonb,available=$5,last_updated=now()
                    WHERE id=$1 AND provider_id=$2 AND enabled RETURNING *''',entity_id,self.provider_id,payload,attrs,available)
                if not row:
                    raise OwnershipError('Entity absent, disabled or owned by another provider')
        self._publish('entity.state_changed',{'state':value,'attributes':attributes or {},'available':available},
                      entity_id=entity_id,device_id=row['device_id'],correlation_id=correlation_id)

    async def emit(self,event_type,payload,*,entity_id=None,device_id=None,correlation_id=None):
        if not event_type.startswith(self.provider_id+'.'):
            raise ValueError('Provider events must use their provider namespace')
        async with db.acquire() as conn:
            if entity_id is not None:
                owned_device=await conn.fetchval('SELECT device_id FROM entities WHERE id=$1 AND provider_id=$2',entity_id,self.provider_id)
                if owned_device is None or (device_id is not None and owned_device!=device_id):
                    raise OwnershipError('Event entity ownership mismatch')
                device_id=owned_device
            if device_id is not None and not await conn.fetchval('SELECT id FROM logical_devices WHERE id=$1 AND provider_id=$2',device_id,self.provider_id):
                raise OwnershipError('Event device ownership mismatch')
        return self._publish(event_type,payload,entity_id=entity_id,device_id=device_id,correlation_id=correlation_id)

    def _publish(self,event_type,payload,*,entity_id=None,device_id=None,correlation_id=None):
        json.dumps(payload,allow_nan=False)
        event_id=str(uuid4())
        event=EventRecord(event_id=event_id,timestamp=datetime.now(timezone.utc).isoformat(),
            module_id='HCM',component=self.provider_id,hardware_id=None,category='integration',
            severity='info',code=event_type,message=event_type,incident_id=correlation_id or event_id,
            metadata={'provider_id':self.provider_id,'entity_id':entity_id,'device_id':device_id,
                      'origin':'provider','correlation_id':correlation_id,'payload':payload})
        self.registry.bus.publish(event)
        return event

    async def service(self,domain,name,arguments,callback,**options):
        await self.registry.services.register(self.provider_id,domain,name,arguments,callback,**options)
