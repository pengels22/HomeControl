"""Denon AVR LAN integration using the documented ASCII control protocol."""
import asyncio, time
from pydantic import BaseModel, ConfigDict, Field
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory
from .http import ProviderHTTPError

class Empty(BaseModel): model_config=ConfigDict(extra='forbid')
class VolumeArgs(BaseModel): model_config=ConfigDict(extra='forbid'); volume_level: float=Field(ge=0,le=1)
class SourceArgs(BaseModel): model_config=ConfigDict(extra='forbid'); source: str=Field(min_length=1,max_length=64)

class DenonTransport:
    def __init__(self,host,port=23,timeout=5): self.host=host; self.port=port; self.timeout=timeout; self.reader=None; self.writer=None
    async def connect(self): self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection(self.host,self.port),self.timeout)
    async def send(self,command):
        if not self.writer: await self.connect()
        self.writer.write((command+'\r').encode()); await self.writer.drain()
        try: return (await asyncio.wait_for(self.reader.readline(),self.timeout)).decode(errors='replace').strip()
        except asyncio.TimeoutError: return ''
    async def close(self):
        if self.writer: self.writer.close(); await self.writer.wait_closed()
        self.reader=self.writer=None

class DenonProvider(Provider):
    info=ProviderInfo('denon_avr','Denon AVR',capabilities={'media_player':True,'lan':True,'commands':True},description='Denon AVR local network control',setup_type='lan',supports_multiple=True,config_schema={'type':'object','properties':{'host':{'type':'string'},'port':{'type':'integer','minimum':1,'maximum':65535},'friendly_name':{'type':'string'}},'required':['host'],'additionalProperties':False},config_flow={'type':'lan','fields':[{'name':'friendly_name','type':'text'},{'name':'host','type':'text','required':True},{'name':'port','type':'integer'}]})
    def __init__(self,transport=None): self.context=None; self.transport=transport; self.task=None; self.device=None; self.entity=None; self.state={'state':'off','power':False,'volume_level':0.0,'muted':False,'source':None,'source_list':[],'available':False}; self.sources=[]; self.commands=0; self.failures=0; self.reconnects=0; self.last_update=None
    async def setup(self,context):
        self.context=context; cfg=context.config; self.transport=self.transport or DenonTransport(cfg['host'],int(cfg.get('port',23))); self.device=await context.device('avr','Denon AVR',available=False); self.entity=await context.entity('media_player','media_player.avr',self.device,cfg.get('friendly_name') or 'Denon AVR')
        await context.service('media_player','turn_on',Empty,self.turn_on,target_required=True,target_domains=('media_player',)); await context.service('media_player','turn_off',Empty,self.turn_off,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_set',VolumeArgs,self.volume_set,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_up',Empty,self.volume_up,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_down',Empty,self.volume_down,target_required=True,target_domains=('media_player',)); await context.service('media_player','mute',Empty,self.mute,target_required=True,target_domains=('media_player',)); await context.service('media_player','unmute',Empty,self.unmute,target_required=True,target_domains=('media_player',)); await context.service('media_player','select_source',SourceArgs,self.select_source,target_required=True,target_domains=('media_player',))
    def parse_line(self,line):
        if not line: return
        if line.startswith('PW'): self.state['power']=line[2:]=='ON'; self.state['state']='on' if self.state['power'] else 'off'
        elif line.startswith('MV') and line[2:4] in {'UP','DOWN'}: pass
        elif line.startswith('MV') and line[2:4]=='FL':
            try: self.state['volume_level']=max(0,min(1,(float(line[4:])+80)/80))
            except ValueError: pass
        elif line.startswith('MU'): self.state['muted']=line[2:]=='ON'
        elif line.startswith('SI'): self.state['source']=line[2:]; self.sources=sorted(set(self.sources+[line[2:]])); self.state['source_list']=self.sources
    async def refresh(self):
        for command in ('PW?','MVFL?','MU?','SI?'):
            response=await self.transport.send(command); self.parse_line(response)
        self.state['available']=True; await self.context.state(self.entity,dict(self.state),attributes={'provider':'denon_avr','host':self.context.config.get('host')},available=True); self.last_update=time.time()
    async def command(self,command):
        response=await self.transport.send(command); self.parse_line(response); self.commands+=1; await self.refresh(); return {'success':True,'entity_id':self.entity,'command':command,'state':dict(self.state)}
    async def turn_on(self,args,target): return await self.command('PWON')
    async def turn_off(self,args,target): return await self.command('PWOFF')
    async def volume_set(self,args,target): return await self.command(f'MVFL{(args.volume_level*80)-80:.1f}')
    async def volume_up(self,args,target): return await self.command('MVUP')
    async def volume_down(self,args,target): return await self.command('MVDOWN')
    async def mute(self,args,target): return await self.command('MUON')
    async def unmute(self,args,target): return await self.command('MUOFF')
    async def select_source(self,args,target): return await self.command('SI'+args.source)
    async def start(self):
        await self.transport.connect(); await self.refresh(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            try:
                line=await asyncio.wait_for(self.transport.reader.readline(),15) if self.transport.reader else ''
                if line: self.parse_line(line.decode(errors='replace').strip()); await self.context.state(self.entity,dict(self.state),attributes={'provider':'denon_avr'},available=True)
                else: await asyncio.sleep(2)
            except asyncio.CancelledError: raise
            except Exception:
                self.failures+=1; self.state['available']=False
                if self.entity: await self.context.availability(self.entity,False)
                await asyncio.sleep(min(30,2+self.failures)); self.reconnects+=1
                try: await self.transport.close(); await self.transport.connect(); await self.refresh()
                except Exception: pass
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        if self.transport: await self.transport.close()
    async def reload(self): await self.stop(); self.transport=DenonTransport(self.context.config['host'],int(self.context.config.get('port',23))); await self.start()
    async def health_check(self): return bool(self.state.get('available'))
    async def diagnostics(self): return Diagnostics(counters={'commands':self.commands,'failures':self.failures,'reconnects':self.reconnects,'sources':len(self.sources)},checks={'connected':bool(self.state.get('available'))})

if 'denon_avr' not in provider_factory.types: provider_factory.register_type('denon_avr',DenonProvider.info,lambda context:DenonProvider())
