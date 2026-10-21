"""HEOS local CLI integration with normalized HCM media entities."""
import asyncio, urllib.parse, time, json
from pydantic import BaseModel, ConfigDict, Field
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory

class Empty(BaseModel): model_config=ConfigDict(extra='forbid')
class VolumeArgs(BaseModel): model_config=ConfigDict(extra='forbid'); volume_level: float=Field(ge=0,le=1)
class GroupVolumeArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    step: int = Field(default=5, ge=1, le=10)
    dry_run: bool = False
class PlayMediaArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    media_content_id: str = Field(min_length=1, max_length=1024)
    media_content_type: str|None = Field(default=None, max_length=64)
    enqueue: str|None = Field(default=None, max_length=32)
    metadata: dict = Field(default_factory=dict)

class HEOSTransport:
    def __init__(self,host,port=1255,timeout=5): self.host=host; self.port=port; self.timeout=timeout; self.reader=None; self.writer=None
    async def connect(self): self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection(self.host,self.port),self.timeout)
    async def command(self,path,params=None):
        if not self.writer: await self.connect()
        query=urllib.parse.urlencode(params or {}); self.writer.write((f'heos://{path}?{query}\r\n').encode()); await self.writer.drain(); line=await asyncio.wait_for(self.reader.readline(),self.timeout); return self.parse(line.decode(errors='replace'))
    def parse(self,line):
        line=line.strip()
        if line.startswith('{'):
            try: envelope=json.loads(line)
            except json.JSONDecodeError: return {}
            heos=envelope.get('heos') or {}
            command=str(heos.get('command') or '')
            payload=envelope.get('payload')
            if command=='player/get_players': params={'players':payload}
            elif command=='group/get_groups': params={'groups':payload}
            elif isinstance(payload,dict): params=payload
            else: params={'payload':payload}
            return {'command':command,'params':params}
        if not line.startswith('heos://'): return {}
        parsed=urllib.parse.urlsplit(line); return {'command':parsed.netloc+parsed.path,'params':dict(urllib.parse.parse_qsl(parsed.query))}
    async def close(self):
        if self.writer: self.writer.close(); await self.writer.wait_closed()
        self.reader=self.writer=None

class HEOSProvider(Provider):
    info=ProviderInfo('heos','HEOS',capabilities={'media_player':True,'lan':True,'commands':True,'groups':True},description='HEOS local network players',setup_type='lan',supports_multiple=True,config_schema={'type':'object','properties':{'host':{'type':'string'},'port':{'type':'integer','minimum':1,'maximum':65535},'friendly_name':{'type':'string'}},'required':['host'],'additionalProperties':False},config_flow={'type':'lan','fields':[{'name':'friendly_name','type':'text'},{'name':'host','type':'text','required':True},{'name':'port','type':'integer'}]})
    def __init__(self,transport=None): self.context=None; self.transport=transport; self.task=None; self.players={}; self.entities={}; self.groups=[]; self.commands=0; self.failures=0; self.last_event=None
    async def setup(self,context): self.context=context; cfg=context.config; self.transport=self.transport or HEOSTransport(cfg['host'],int(cfg.get('port',1255))); await context.service('media_player','play',Empty,self.play,target_required=True,target_domains=('media_player',)); await context.service('media_player','pause',Empty,self.pause,target_required=True,target_domains=('media_player',)); await context.service('media_player','stop',Empty,self.stop_playback,target_required=True,target_domains=('media_player',)); await context.service('media_player','next',Empty,self.next,target_required=True,target_domains=('media_player',)); await context.service('media_player','previous',Empty,self.previous,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_set',VolumeArgs,self.volume_set,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_up',Empty,self.volume_up,target_required=True,target_domains=('media_player',)); await context.service('media_player','volume_down',Empty,self.volume_down,target_required=True,target_domains=('media_player',)); await context.service('media_player','group_volume_up',GroupVolumeArgs,self.group_volume_up,target_required=True,target_domains=('media_player',)); await context.service('media_player','group_volume_down',GroupVolumeArgs,self.group_volume_down,target_required=True,target_domains=('media_player',)); await context.service('media_player','mute',Empty,self.mute,target_required=True,target_domains=('media_player',)); await context.service('media_player','unmute',Empty,self.unmute,target_required=True,target_domains=('media_player',)); await context.service('media_player','play_media',PlayMediaArgs,self.play_media,target_required=True,target_domains=('media_player',))
    async def discover(self):
        await self.refresh_groups()
        response=await self.transport.command('player/get_players'); raw=response.get('params',{}).get('players',[])
        try: items=json.loads(raw) if isinstance(raw,str) else raw
        except json.JSONDecodeError: items=[]
        if not isinstance(items,list): items=[]
        for item in items:
            player_id=str(item.get('pid') or item.get('player_id')); name=item.get('name') or player_id; device=await self.context.device('player:'+player_id,name,available=True); entity=await self.context.entity('player:'+player_id,'media_player.player_'+player_id.replace('-','_'),device,name); self.players[player_id]=item; self.entities[player_id]=entity; await self.refresh_player(player_id)
        return len(items)
    async def refresh_groups(self):
        response = await self.transport.command('group/get_groups')
        raw = response.get('params', {}).get('groups', [])
        try: groups = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError: groups = []
        self.groups = groups if isinstance(groups, list) else []
        return self.groups
    async def refresh_player(self,pid):
        response=await self.transport.command('player/get_now_playing_media',{'pid':pid}); p=response.get('params',{}); state={'state':p.get('state','idle'),'power':True,'volume_level':float(p.get('volume','0'))/100,'muted':p.get('mute')=='on','source':p.get('type'),'media_title':p.get('song'),'media_artist':p.get('artist'),'media_album':p.get('album'),'available':True}; await self.context.state(self.entities[pid],state,attributes={'provider':'heos','player_id':pid},available=True)
    async def command(self,pid,path,params=None):
        await self.transport.command(path,{'pid':pid,**(params or {})}); self.commands+=1; await self.refresh_player(pid); return {'success':True,'entity_id':self.entities[pid],'command':path}
    def pid(self,target):
        for pid,eid in self.entities.items():
            if eid==target: return pid
        raise LookupError('HEOS target unavailable')
    async def play(self,a,t): return await self.command(self.pid(t),'player/play')
    async def pause(self,a,t): return await self.command(self.pid(t),'player/pause')
    async def stop_playback(self,a,t): return await self.command(self.pid(t),'player/stop')
    async def next(self,a,t): return await self.command(self.pid(t),'player/play_next')
    async def previous(self,a,t): return await self.command(self.pid(t),'player/play_previous')
    async def play_media(self,a,t):
        pid=self.pid(t)
        if len(json.dumps(a.metadata, separators=(',', ':'))) > 4096:
            raise ValueError('Media metadata exceeds limit')
        if a.media_content_type == 'favorite':
            return await self.command(pid,'browse/play_input',{'input':a.media_content_id})
        return await self.command(pid,'player/play_url',{'url':a.media_content_id})
    async def volume_set(self,a,t): return await self.command(self.pid(t),'player/set_volume',{'level':round(a.volume_level*100)})
    async def volume_up(self,a,t): return await self.command(self.pid(t),'player/volume_up')
    async def volume_down(self,a,t): return await self.command(self.pid(t),'player/volume_down')
    def group_for_pid(self, pid):
        for group in self.groups:
            if not isinstance(group, dict): continue
            members = group.get('players') or group.get('members') or []
            ids = {str(group.get(key)) for key in ('leader', 'leader_pid', 'pid') if group.get(key) is not None}
            if isinstance(members, list):
                for member in members:
                    if isinstance(member, dict): ids.update(str(member.get(key)) for key in ('pid', 'player_id') if member.get(key) is not None)
                    elif member is not None: ids.add(str(member))
            if str(pid) in ids: return group
        return None
    async def _group_volume(self, direction, args, target):
        pid = self.pid(target)
        await self.refresh_groups()
        group = self.group_for_pid(pid)
        if group is None:
            return {'status': 'not_grouped', 'entity_id': target, 'direction': direction}
        gid = group.get('gid') or group.get('group_id')
        if gid is None:
            return {'status': 'provider_unavailable', 'entity_id': target, 'direction': direction}
        if args.dry_run:
            return {'status': 'dry_run', 'entity_id': target, 'group_id': str(gid), 'direction': direction, 'step': args.step}
        await self.transport.command(f'group/volume_{direction}', {'gid': gid, 'step': args.step})
        self.commands += 1
        return {'status': 'success', 'entity_id': target, 'group_id': str(gid), 'direction': direction, 'step': args.step}
    async def group_volume_up(self,a,t): return await self._group_volume('up', a, t)
    async def group_volume_down(self,a,t): return await self._group_volume('down', a, t)
    async def mute(self,a,t): return await self.command(self.pid(t),'player/set_mute',{'state':'on'})
    async def unmute(self,a,t): return await self.command(self.pid(t),'player/set_mute',{'state':'off'})
    async def start(self): await self.transport.connect(); await self.discover(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            try:
                line=await asyncio.wait_for(self.transport.reader.readline(),30)
                event=self.transport.parse(line.decode(errors='replace'))
                if event: self.last_event=time.time(); pid=event.get('params',{}).get('pid');
                if event and pid in self.entities: await self.refresh_player(pid)
            except asyncio.CancelledError: raise
            except Exception:
                self.failures+=1; await asyncio.sleep(min(30,2+self.failures))
                try: await self.transport.close(); await self.transport.connect(); await self.discover()
                except Exception: pass
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        if self.transport: await self.transport.close()
    async def reload(self): await self.stop(); self.transport=HEOSTransport(self.context.config['host'],int(self.context.config.get('port',1255))); await self.start()
    async def health_check(self): return bool(self.entities)
    async def diagnostics(self): return Diagnostics(counters={'players':len(self.players),'groups':len(self.groups),'commands':self.commands,'failures':self.failures},checks={'connected':bool(self.entities)})

if 'heos' not in provider_factory.types: provider_factory.register_type('heos',HEOSProvider.info,lambda context:HEOSProvider())
