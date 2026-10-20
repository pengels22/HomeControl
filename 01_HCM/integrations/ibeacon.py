"""iBeacon consumer built on the native HCM Bluetooth scanner."""
import asyncio, time, uuid, hashlib
from pydantic import BaseModel, ConfigDict, Field
from ..bluetooth import scanner, Advertisement
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory

class IBeaconProvider(Provider):
    info=ProviderInfo('ibeacon','iBeacon',capabilities={'presence':True,'bluetooth':True},description='Native Bluetooth iBeacon presence',setup_type='bluetooth',supports_multiple=True,config_schema={'type':'object','properties':{'uuid':{'type':'string'},'major':{'type':'integer','minimum':0,'maximum':65535},'minor':{'type':'integer','minimum':0,'maximum':65535},'friendly_name':{'type':'string'},'timeout':{'type':'integer','minimum':5},'adapter':{'type':'string'}},'required':['uuid','major','minor'],'additionalProperties':False},config_flow={'type':'bluetooth','fields':[{'name':'friendly_name','type':'text'},{'name':'uuid','type':'text','required':True},{'name':'major','type':'integer','required':True},{'name':'minor','type':'integer','required':True},{'name':'timeout','type':'integer'},{'name':'adapter','type':'text'}]})
    def __init__(self): self.context=None; self.device=None; self.present=None; self.last_seen=None; self.rssi=None; self.samples=[]; self.task=None; self.unsubscribe=None; self.advertisements=0
    @staticmethod
    def parse(advertisement):
        for company,data in advertisement.manufacturer_data.items():
            raw=bytes(data)
            if int(company)!=0x004c or len(raw)<23 or raw[:2]!=b'\x02\x15': continue
            beacon_uuid=str(uuid.UUID(bytes=raw[2:18])).lower(); major=int.from_bytes(raw[18:20],'big'); minor=int.from_bytes(raw[20:22],'big'); tx=int.from_bytes(raw[22:23],'big',signed=True)
            return {'uuid':beacon_uuid,'major':major,'minor':minor,'tx_power':tx,'rssi':advertisement.rssi,'address':advertisement.address,'timestamp':advertisement.timestamp}
        return None
    def identity(self): return f"{self.context.config['uuid'].lower()}:{int(self.context.config['major'])}:{int(self.context.config['minor'])}"
    async def setup(self,context):
        self.context=context; name=context.config.get('friendly_name') or 'iBeacon'; self.device=await context.device(self.identity(),name,available=False); suffix=hashlib.sha1(self.identity().encode()).hexdigest()[:8]; self.present_entity=await context.entity('present',f'binary_sensor.present_{suffix}',self.device,name); self.rssi_entity=await context.entity('rssi',f'sensor.rssi_{suffix}',self.device,'RSSI',unit='dBm'); self.last_seen_entity=await context.entity('last_seen',f'sensor.last_seen_{suffix}',self.device,'Last Seen'); self.unsubscribe=scanner.subscribe(self._on_advertisement)
    async def _on_advertisement(self,advertisement):
        beacon=self.parse(advertisement)
        if not beacon or beacon['uuid']!=self.context.config['uuid'].lower() or beacon['major']!=int(self.context.config['major']) or beacon['minor']!=int(self.context.config['minor']): return
        self.advertisements+=1; was=self.present is True; self.present=True; self.last_seen=time.monotonic(); self.samples=(self.samples+[beacon['rssi']])[-8:] if beacon['rssi'] is not None else self.samples; self.rssi=round(sum(self.samples)/len(self.samples),1) if self.samples else None
        await self.context.device(self.identity(),self.context.config.get('friendly_name') or 'iBeacon',available=True); await self.context.state(self.present_entity,True,attributes={'provider':'ibeacon','uuid':beacon['uuid'],'major':beacon['major'],'minor':beacon['minor']},available=True); await self.context.state(self.rssi_entity,self.rssi,attributes={'raw_rssi':beacon['rssi'],'tx_power':beacon['tx_power']},available=True); await self.context.state(self.last_seen_entity,beacon['timestamp'],attributes={'provider':'ibeacon'},available=True)
        if not was: await self.context.emit('ibeacon.entered',{'beacon_id':self.identity()})
    async def start(self):
        if not scanner.running: await scanner.start()
        self.task=asyncio.create_task(self._expiry())
    async def _expiry(self):
        while True:
            await asyncio.sleep(max(1,int(self.context.config.get('timeout',60))))
            if self.present and self.last_seen and time.monotonic()-self.last_seen>=int(self.context.config.get('timeout',60)):
                self.present=False; await self.context.availability(self.present_entity,True); await self.context.state(self.present_entity,False,attributes={'provider':'ibeacon'},available=True); await self.context.emit('ibeacon.left',{'beacon_id':self.identity()})
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        if self.unsubscribe: self.unsubscribe(); self.unsubscribe=None
    async def reload(self): await self.stop(); await self.start()
    async def health_check(self): return scanner.running
    async def diagnostics(self): return Diagnostics(counters={'advertisements':self.advertisements,'samples':len(self.samples)},checks={'scanner_running':scanner.running,'present':bool(self.present)})

if 'ibeacon' not in provider_factory.types: provider_factory.register_type('ibeacon',IBeaconProvider.info,lambda context:IBeaconProvider())
