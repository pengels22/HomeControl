"""SmartThings cloud integration: capability normalization and safe commands."""
import asyncio
import hashlib
import time
from .. import db
from pydantic import BaseModel, ConfigDict, Field
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .oauth import OAuthMetadata, OAuthHTTPClient, refresh_scheduler
from .webhooks import WebhookGuard
from .weather import record_poll
from . import secrets as secret_store

AUTH='https://api.smartthings.com/oauth/authorize'; TOKEN='https://api.smartthings.com/oauth/token'; API='https://api.smartthings.com/v1'

class SwitchCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')

class SmartThingsProvider(Provider):
    info=ProviderInfo('smartthings','SmartThings',capabilities={'devices':True,'events':True,'commands':True,'webhooks':True},description='SmartThings devices, state and safe commands',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'client_id':{'type':'string'},'redirect_uri':{'type':'string'},'interval':{'type':'integer','minimum':60},'webhook_secret':{'type':'string'}},'additionalProperties':False},config_flow={'type':'oauth','credential_kinds':['client_secret'],'scopes':['r:devices:*','x:devices:*'],'fields':[{'name':'client_id','type':'text','required':True},{'name':'redirect_uri','type':'text','required':True},{'name':'interval','type':'duration'}]})
    def __init__(self,client=None):
        self.context=None; self.client=client or ProviderHTTP(timeout=15); self.task=None; self.devices={}; self.entities={}; self.last=None; self.last_error=None; self.unsupported=0; self.commands=0
        self.guard=WebhookGuard('smartthings')

    async def setup(self,context):
        self.context=context
        await context.service('switch','turn_on',SwitchCommand,self.turn_on,target_required=True,target_domains=('switch',))
        await context.service('switch','turn_off',SwitchCommand,self.turn_off,target_required=True,target_domains=('switch',))

    async def _token(self):
        bundle=await self.context.account_credential()
        if isinstance(bundle,str): bundle={'access_token':bundle}
        if self.context.account_ref:
            try: expires=(await secret_store.get_record(self.context.account_ref))['metadata'].get('expires_at')
            except Exception: expires=None
            if expires and expires-time.time()<60 and bundle.get('refresh_token'):
                secret=await self.context.credential(); client_id=self.context.config.get('client_id')
                async def request(url,data,style): return (await self.client.json('POST',url,form_body=data,headers={'Accept':'application/json'}))[0]
                token=await OAuthHTTPClient(request).refresh(OAuthMetadata(AUTH,TOKEN),bundle['refresh_token'],client_id,secret)
                refreshed={'access_token':token.access_token,'refresh_token':token.refresh_token or bundle.get('refresh_token'),'token_type':token.token_type,'scopes':list(token.scopes)}
                ref=await secret_store.put('smartthings','oauth_access_token',refreshed,metadata={'expires_at':token.expires_at}); old=self.context.account_ref; self.context.account_ref=ref
                async with db.acquire() as conn: await conn.execute("UPDATE integration_instances SET account_ref=$2,status='connected',last_success=now(),last_error=NULL,updated_at=now() WHERE instance_id=$1",self.context.instance_id,ref)
                await secret_store.revoke(old); bundle=refreshed
        return bundle.get('access_token')

    async def _json(self,method,path,**kwargs):
        token=await self._token(); data,status=await self.client.json(method,API+path,headers={'Authorization':f'Bearer {token}','Accept':'application/json'},**kwargs); self.last=asyncio.get_running_loop().time(); return data

    def _mapping(self,capability):
        return {'switch':('switch','state'),'switchLevel':('light','level'),'temperatureMeasurement':('sensor','temperature'),'relativeHumidityMeasurement':('sensor','humidity'),'contactSensor':('binary_sensor','contact'),'motionSensor':('binary_sensor','motion'),'presenceSensor':('device_tracker','presence'),'battery':('sensor','battery'),'washerOperatingState':('sensor','job_state'),'dryerOperatingState':('sensor','job_state'),'washerMachineState':('sensor','machine_state'),'dryerMachineState':('sensor','machine_state')}.get(capability)

    def _value(self,capability,attr):
        if not isinstance(attr,dict): return None
        value=attr.get('value')
        if capability in {'contactSensor','motionSensor','presenceSensor'}: return value
        if capability=='switchLevel' and isinstance(value,dict): return value.get('level')
        return value

    async def discover(self):
        response=await self._json('GET','/devices'); devices=response.get('items',[]) if isinstance(response,dict) else []
        seen=set()
        for device in devices:
            external=device.get('deviceId');
            if not external: continue
            seen.add(external); name=device.get('label') or device.get('name') or external
            hcm_device=await self.context.device(external,name,available=device.get('healthState')!='OFFLINE')
            self.devices[external]=hcm_device
            capabilities=[]
            for component in device.get('components',[]):
                for cap in component.get('capabilities',[]):
                    capability=cap.get('id') if isinstance(cap,dict) else cap; mapping=self._mapping(capability)
                    if not mapping: self.unsupported+=1; continue
                    domain,suffix=mapping; external_entity=f'{external}:{component.get("id","main")}:{capability}'
                    stable_suffix=f'{suffix}_{hashlib.sha1(external_entity.encode()).hexdigest()[:8]}'
                    entity=await self.context.entity(external_entity,f'{domain}.{stable_suffix}',hcm_device,name,device_class=suffix)
                    self.entities[external_entity]=(entity,external,component.get('id','main'),capability,domain,suffix); capabilities.append((component.get('id','main'),capability))
            await self.sync_device(external,capabilities)
        for external,device_id in list(self.devices.items()):
            if external not in seen: await self.context.device(external,'SmartThings device',available=False)
        return len(seen)

    async def sync_device(self,external,capabilities=None):
        state=await self._json('GET',f'/devices/{external}/states'); items=state.get('components',[]) if isinstance(state,dict) else []
        flat={(c.get('id'),cap.get('id'),attr.get('id')):attr for c in items for cap in c.get('capabilities',[]) for attr in cap.get('attributes',[])}
        for key,(entity,device,component,capability,domain,suffix) in self.entities.items():
            if device!=external: continue
            attr=next((v for (comp,cap,_),v in flat.items() if comp==component and cap==capability),None); value=self._value(capability,attr)
            if value is not None: await self.context.state(entity,value,attributes={'provider':'smartthings','capability':capability,'component':component},available=True)
        await self.context.emit('smartthings.device_state_changed',{'device_id':external})

    async def command(self,entity_id,value):
        row=next((x for x in self.entities.values() if x[0]==entity_id),None)
        if not row: raise LookupError('SmartThings target unavailable')
        _,device,component,capability,_,_=row
        if capability!='switch': raise ValueError('SmartThings capability is not commandable')
        result=await self._json('POST',f'/devices/{device}/commands',json_body={'commands':[{'component':component,'capability':'switch','command':'on' if value=='on' else 'off'}]})
        self.commands+=1; return {'accepted':True,'entity_id':entity_id,'device_id':device,'capability':capability,'result_id':result.get('requestId') if isinstance(result,dict) else None}
    async def turn_on(self,args,target): return await self.command(target,'on')
    async def turn_off(self,args,target): return await self.command(target,'off')

    async def handle_webhook(self,payload,signature,nonce,secret):
        self.guard.verify(payload,signature,secret,nonce); event=payload if isinstance(payload,dict) else {}
        device=event.get('deviceId') or event.get('data',{}).get('deviceId')
        if device: await self.sync_device(device)
        return {'accepted':True,'device_id':device}
    async def start(self): await self.discover(); await record_poll(self.context,True); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',300))))
            try: await self.discover(); await record_poll(self.context,True)
            except Exception as exc: self.last_error=type(exc).__name__; await record_poll(self.context,False,self.last_error)
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def reload(self): await self.stop(); self.client=ProviderHTTP(timeout=15); await self.start()
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'devices':len(self.devices),'entities':len(self.entities),'unsupported_capabilities':self.unsupported,'commands':self.commands},checks={'account_connected':bool(self.context and self.context.account_ref),'webhook_ready':True})

if 'smartthings' not in provider_factory.types: provider_factory.register_type('smartthings',SmartThingsProvider.info,lambda context:SmartThingsProvider())
