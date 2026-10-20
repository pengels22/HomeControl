"""Failure-isolated provider lifecycle; independent of output and safety loops."""
import asyncio
import json
from dataclasses import dataclass
from .registry import Registry
from .provider import Diagnostics
from .factory import provider_factory
from .oauth import refresh_scheduler
from .. import db
from .http import ProviderHTTPError


@dataclass
class Entry:
    provider: object
    enabled: bool
    configured: bool
    status: str = 'disabled'
    last_error: str | None = None


class Runtime:
    def __init__(self,registry=None,*,timeout=5,health_interval=30):
        self.registry=registry or Registry()
        self.timeout=timeout
        self.health_interval=health_interval
        self.entries={}
        self.task=None
        self.locks={}
        self.instances={}
        self.instance_contexts={}
        self.automation_engine=None

    def attach(self,provider,*,enabled=False,configured=True):
        key=provider.info.provider_id
        if key in self.entries:
            raise ValueError('Provider already attached')
        self.entries[key]=Entry(provider,enabled,configured)
        self.locks[key]=asyncio.Lock()

    def register_type(self,provider_id,metadata,factory): provider_factory.register_type(provider_id,metadata,factory)

    def attach_instance(self,instance_id,provider_id,context,*,enabled=True,configured=True):
        if instance_id in self.instances: raise ValueError('Instance already attached')
        provider=provider_factory.create(provider_id,context)
        self.instances[instance_id]=Entry(provider,enabled,configured)
        self.instance_contexts[instance_id]=context
        self.locks[instance_id]=asyncio.Lock()

    async def restore_instances(self):
        async with db.acquire() as conn:
            rows=await conn.fetch('SELECT instance_id,provider_id,display_name,enabled,configured,config,credential_ref,account_ref FROM integration_instances ORDER BY created_at')
        for row in rows:
            key=str(row['instance_id'])
            if row['provider_id'] not in provider_factory.types:
                async with db.acquire() as conn: await conn.execute("UPDATE integration_instances SET status='provider_missing',last_error='Provider implementation unavailable',updated_at=now() WHERE instance_id=$1",row['instance_id'])
                continue
            try:
                config=row['config'] or {}
                if isinstance(config,str): config=json.loads(config)
                context=self.registry.context(row['provider_id'],key,config=config,credential_ref=row['credential_ref'],account_ref=row['account_ref'],display_name=row['display_name'])
                self.attach_instance(key,row['provider_id'],context,enabled=row['enabled'],configured=row['configured'])
                if row['enabled'] and row['configured']: await self.start_instance(key)
                else:
                    status='disabled' if not row['enabled'] else 'configuration_required'
                    async with db.acquire() as conn: await conn.execute('UPDATE integration_instances SET status=$2,updated_at=now() WHERE instance_id=$1',row['instance_id'],status)
            except Exception as exc:
                async with db.acquire() as conn: await conn.execute("UPDATE integration_instances SET status='error',last_error=$2,updated_at=now() WHERE instance_id=$1",row['instance_id'],f'startup failed ({type(exc).__name__})')

    async def start_instance(self,instance_id):
        async with self.locks[instance_id]:
            entry=self.instances[instance_id]
            if not entry.enabled or not entry.configured:
                entry.status='disabled' if not entry.enabled else 'configuration_required'; return
            ok,_=await self._operation_instance(instance_id,'setup',self.instance_contexts[instance_id])
            if ok: ok,_=await self._operation_instance(instance_id,'start')
            if ok: await self._operation_instance(instance_id,'health_check')
            else: entry.status='error'

    async def _operation_instance(self,key,operation,*args):
        try:
            result=await asyncio.wait_for(getattr(self.instances[key].provider,operation)(*args),self.timeout)
            self.instances[key].status='connected' if operation=='health_check' and result is True else self.instances[key].status
            try:
                async with db.acquire() as conn: await conn.execute('UPDATE integration_instances SET status=$2,last_error=NULL,updated_at=now() WHERE instance_id=$1',key,self.instances[key].status)
            except Exception: pass
            return True,result
        except Exception as exc:
            self.instances[key].status='authentication_required' if isinstance(exc,ProviderHTTPError) and exc.category in {'authentication','authorization'} else 'degraded'; self.instances[key].last_error=f'{operation} failed ({getattr(exc,"category",type(exc).__name__)})'
            try:
                async with db.acquire() as conn: await conn.execute('UPDATE integration_instances SET status=$2,last_error=$3,updated_at=now() WHERE instance_id=$1',key,self.instances[key].status,self.instances[key].last_error)
            except Exception: pass
            return False,None

    async def stop_instance(self,instance_id):
        if instance_id in self.instances:
            refresh_scheduler.cancel(instance_id)
            await self._operation_instance(instance_id,'stop'); self.instances[instance_id].status='disabled'; await self.registry.services.unregister_instance(self.instance_contexts[instance_id].provider_id,instance_id)

    async def reload_instance(self,instance_id):
        if instance_id not in self.instances: raise LookupError('Instance runtime unavailable')
        async with self.locks[instance_id]:
            await self._operation_instance(instance_id,'reload'); await self._operation_instance(instance_id,'health_check')

    async def _status(self,key,status,error=None):
        entry=self.entries[key]
        entry.status=status
        entry.last_error=error
        try:
            await self.registry.status(key,status,error)
        except Exception:
            entry.status='error'
            entry.last_error='Registry status persistence failed'

    async def _operation(self,key,operation,*args):
        try:
            result=await asyncio.wait_for(getattr(self.entries[key].provider,operation)(*args),self.timeout)
            return True,result
        except Exception as exc:
            await self._status(key,'degraded',f'{operation} failed ({type(exc).__name__})')
            return False,None

    async def start_provider(self,key):
        async with self.locks[key]:
            entry=self.entries[key]
            try:
                await self.registry.register(entry.provider.info,enabled=entry.enabled,configured=entry.configured)
            except Exception:
                await self._status(key,'error','Provider registration failed')
                return
            if not entry.enabled or not entry.configured:
                await self._status(key,'disabled' if not entry.enabled else 'configuration_required')
                return
            await self._status(key,'starting')
            ok,_=await self._operation(key,'setup',self.registry.context(key))
            if ok:
                ok,_=await self._operation(key,'start')
            if not ok:
                error=entry.last_error
                await self._operation(key,'stop')
                await self._status(key,'error',error)
                return
            await self._health(key)

    async def _health(self,key):
        ok,healthy=await self._operation(key,'health_check')
        if ok:
            await self._status(key,'connected' if healthy is True else 'degraded',None if healthy is True else 'Health check reported unhealthy')

    async def health(self,key):
        async with self.locks[key]:
            entry=self.entries[key]
            if entry.status in {'connected','degraded'}:
                await self._health(key)

    async def reload(self,key):
        async with self.locks[key]:
            entry=self.entries[key]
            if not entry.enabled or not entry.configured or entry.status not in {'connected','degraded'}:
                raise LookupError('Provider is not running')
            ok,_=await self._operation(key,'reload')
            if ok:
                await self._health(key)

    async def diagnostics(self,key):
        async with self.locks[key]:
            ok,value=await self._operation(key,'diagnostics')
            if ok and isinstance(value,Diagnostics):
                return value.model_dump()
            if ok:
                await self._status(key,'degraded','Invalid public diagnostics contract')
            return {'counters':{},'checks':{}}

    async def start(self):
        if self.task is not None and not self.task.done():
            return
        self.task=asyncio.create_task(self._run())

    async def _run(self):
        await asyncio.gather(*(self.start_provider(key) for key in self.entries))
        while True:
            await asyncio.sleep(self.health_interval)
            await asyncio.gather(*(self.health(key) for key in self.entries))

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
            self.task=None
        for key,entry in self.entries.items():
            async with self.locks[key]:
                if entry.enabled:
                    await self._operation(key,'stop')
                    await self._status(key,'stopped',entry.last_error)
        self.registry.services.handlers.clear()
        for instance_id in list(self.instances):
            await self.stop_instance(instance_id)


runtime=Runtime()
