"""Failure-isolated provider lifecycle; independent of output and safety loops."""
import asyncio
from dataclasses import dataclass
from .registry import Registry
from .provider import Diagnostics


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

    def attach(self,provider,*,enabled=False,configured=True):
        key=provider.info.provider_id
        if key in self.entries:
            raise ValueError('Provider already attached')
        self.entries[key]=Entry(provider,enabled,configured)
        self.locks[key]=asyncio.Lock()

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


runtime=Runtime()
