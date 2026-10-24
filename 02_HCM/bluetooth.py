"""Native BLE observation pipeline with optional Linux/BlueZ backend."""
import asyncio, time
from dataclasses import dataclass, field
from collections import OrderedDict

@dataclass(frozen=True)
class Advertisement:
    adapter: str
    address: str
    address_type: str|None = None
    name: str|None = None
    rssi: int|None = None
    manufacturer_data: dict = field(default_factory=dict)
    service_uuids: tuple[str,...] = ()
    service_data: dict = field(default_factory=dict)
    tx_power: int|None = None
    connectable: bool|None = None
    timestamp: float = field(default_factory=time.time)

class BluetoothScanner:
    def __init__(self,adapter='auto',backend=None,cache_size=256,expiry=300):
        self.adapter=adapter; self.backend=backend; self.cache_size=cache_size; self.expiry=expiry; self.cache=OrderedDict(); self.subscribers=set(); self.running=False; self.count=0; self.restarts=0; self.last_error=None; self.task=None; self.tasks=set(); self.pending={}
    def subscribe(self,callback): self.subscribers.add(callback); return lambda: self.subscribers.discard(callback)
    def observe(self,advertisement):
        if not isinstance(advertisement,Advertisement): raise TypeError('Advertisement required')
        self.count+=1; self.cache[advertisement.address]=(time.monotonic(),advertisement); self.cache.move_to_end(advertisement.address)
        while len(self.cache)>self.cache_size: self.cache.popitem(last=False)
        for callback in tuple(self.subscribers):
            try: result=callback(advertisement); 
            except Exception: continue
            if asyncio.iscoroutine(result):
                if advertisement.address in self.pending: result.close(); continue
                task=asyncio.create_task(result); self.tasks.add(task); self.pending[advertisement.address]=task
                def done(finished,address=advertisement.address):
                    self.tasks.discard(finished); self.pending.pop(address,None)
                    if not finished.cancelled(): finished.exception()
                task.add_done_callback(done)
    def recent(self):
        now=time.monotonic(); stale=[key for key,(seen,_) in self.cache.items() if now-seen>self.expiry]
        for key in stale: self.cache.pop(key,None)
        return [item[1] for item in self.cache.values()]
    async def start(self):
        if self.running: return
        self.running=True
        if self.backend and hasattr(self.backend,'start'):
            try: await self.backend.start(self.observe,self.adapter)
            except Exception as exc: self.last_error=type(exc).__name__; self.running=False
    async def stop(self):
        self.running=False
        if self.backend and hasattr(self.backend,'stop'): await self.backend.stop()
        for task in tuple(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks,return_exceptions=True)
        self.tasks.clear(); self.pending.clear()
    async def restart(self): self.restarts+=1; await self.stop(); await self.start()
    def status(self): return {'adapter':self.adapter,'running':self.running,'advertisement_count':self.count,'recent_device_count':len(self.recent()),'restart_count':self.restarts,'last_error':self.last_error}

class BleakBackend:
    """Optional BlueZ backend; importing bleak is deferred until runtime."""
    def __init__(self): self.scanner=None
    async def start(self,callback,adapter):
        try:
            from bleak import BleakScanner
        except ImportError: raise RuntimeError('BLE backend unavailable')
        device=adapter if adapter!='auto' else None
        def detection(dev,adv):
            callback(Advertisement(adapter=adapter,address=dev.address,name=dev.name,rssi=adv.rssi,manufacturer_data=dict(adv.manufacturer_data or {}),service_uuids=tuple(adv.service_uuids or ()),service_data=dict(adv.service_data or {}),tx_power=getattr(adv,'tx_power',None)))
        self.scanner=BleakScanner(detection_callback=detection,device=device); await self.scanner.start()
    async def stop(self):
        if self.scanner: await self.scanner.stop(); self.scanner=None

scanner=BluetoothScanner(backend=BleakBackend())

from fastapi import APIRouter, Depends
from .auth import require_user
bluetooth_router=APIRouter(prefix='/api/v1/bluetooth',dependencies=[Depends(require_user)])

@bluetooth_router.get('/status')
async def status(): return scanner.status()

@bluetooth_router.get('/discovery')
async def discovery():
    return {'devices':[{'address':a.address,'name':a.name,'rssi':a.rssi,'adapter':a.adapter,'service_uuids':list(a.service_uuids),'last_seen':a.timestamp} for a in scanner.recent()]}
