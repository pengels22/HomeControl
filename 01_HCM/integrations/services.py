"""Discoverable declarations and in-process handlers; no public execution API."""
import asyncio
import json
from dataclasses import dataclass
from pydantic import BaseModel
from .. import db
from .registry import identifier, OwnershipError


@dataclass
class Handler:
    arguments: type[BaseModel]
    callback: object
    target_required: bool
    target_domains: tuple[str,...]
    physical: bool


class Services:
    def __init__(self,registry):
        self.registry=registry
        self.handlers={}

    async def register(self,provider_id,domain,name,arguments,callback,*,target_required=False,target_domains=(),mutates_physical_state=False):
        identifier(domain); identifier(name)
        if not isinstance(arguments,type) or not issubclass(arguments,BaseModel):
            raise TypeError('Arguments must use a Pydantic model')
        if arguments.model_config.get('extra') != 'forbid':
            raise ValueError('Service arguments must reject unknown fields')
        for target_domain in target_domains:
            identifier(target_domain)
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError('Service handler must be async')
        async with db.acquire() as conn:
            await conn.execute('''INSERT INTO service_definitions
                (provider_id,domain,service_name,argument_schema,target_requirements,mutates_physical_state)
                VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6)
                ON CONFLICT(provider_id,domain,service_name) DO UPDATE SET
                argument_schema=EXCLUDED.argument_schema,target_requirements=EXCLUDED.target_requirements,
                mutates_physical_state=EXCLUDED.mutates_physical_state''',provider_id,domain,name,
                json.dumps(arguments.model_json_schema()),json.dumps({'required':target_required,'domains':list(target_domains)}),mutates_physical_state)
        self.handlers[(provider_id,domain,name)]=Handler(arguments,callback,target_required,tuple(target_domains),mutates_physical_state)

    async def inspect(self,provider_id=None):
        rows=await self.registry.inspect('services',provider_id)
        providers={r['provider_id']:r for r in await self.registry.inspect('integrations',provider_id)}
        for row in rows:
            provider=providers[row['provider_id']]
            row['available']=bool((row['provider_id'],row['domain'],row['service_name']) in self.handlers
                and provider['enabled'] and provider['configured'] and provider['status']=='connected'
                and not row['mutates_physical_state'])
        return rows

    async def invoke(self,provider_id,domain,name,arguments,*,target_entity_id=None,timeout=5):
        handler=self.handlers.get((provider_id,domain,name))
        if handler is None:
            raise LookupError('Service handler unavailable')
        if handler.physical:
            raise PermissionError('Physical services are outside the foundation slice')
        validated=handler.arguments.model_validate(arguments)
        if handler.target_required and target_entity_id is None:
            raise ValueError('Target entity required')
        async with db.acquire() as conn:
            active=await conn.fetchval('''SELECT enabled AND configured AND status='connected'
                FROM integration_providers WHERE provider_id=$1''',provider_id)
            if not active:
                raise LookupError('Provider unavailable')
            if target_entity_id is not None:
                target=await conn.fetchrow('SELECT provider_id,domain,enabled,available FROM entities WHERE id=$1',target_entity_id)
                if not target or target['provider_id']!=provider_id:
                    raise OwnershipError('Target belongs to another provider')
                if not target['enabled'] or not target['available']:
                    raise LookupError('Target unavailable')
                if handler.target_domains and target['domain'] not in handler.target_domains:
                    raise ValueError('Unsupported target domain')
        try:
            return await asyncio.wait_for(handler.callback(validated,target_entity_id),timeout)
        except Exception as exc:
            # Never expose arbitrary provider exception text (possibly credentials).
            raise RuntimeError(f'Service failed ({type(exc).__name__})') from None
