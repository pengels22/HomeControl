"""SmartThings cloud integration: capability normalization and safe commands."""
import asyncio
import hashlib
import time
import base64, re
from datetime import datetime, timezone
from urllib.parse import urlparse
from .. import db
from fastapi import APIRouter, Request, HTTPException
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from pydantic import BaseModel, ConfigDict, Field
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .oauth import OAuthMetadata, OAuthHTTPClient, refresh_scheduler
from .webhooks import WebhookGuard
from .weather import record_poll
from . import secrets as secret_store

AUTH='https://api.smartthings.com/oauth/authorize'; TOKEN='https://api.smartthings.com/oauth/token'; API='https://api.smartthings.com/v1'

def digest_value(body): return 'SHA-256='+base64.b64encode(hashlib.sha256(body).digest()).decode()

class SmartThingsRequestVerifier:
    def __init__(self,client=None,skew=300): self.client=client; self.skew=skew; self.keys={}
    def _auth(self,value):
        if not value or not value.startswith('Signature '): raise ValueError('Malformed authorization signature')
        fields={}
        for part in re.split(r',\s*',value[10:]):
            key,sep,val=part.partition('=')
            if not sep or len(val)<2 or val[0]!='"' or not val.endswith('"'): raise ValueError('Malformed authorization signature')
            fields[key.strip()]=val[1:-1]
        if fields.get('algorithm','').lower() not in {'rsa-sha256','rsa_sha256'}: raise ValueError('Unsupported signature algorithm')
        headers=fields.get('headers','').split()
        if 'keyId' not in fields or 'signature' not in fields or not {'(request-target)','digest','date'}.issubset(headers): raise ValueError('Incomplete authorization signature')
        return fields,headers
    async def _key(self,key_id):
        cached=self.keys.get(key_id)
        if cached and cached[0]>time.time(): return cached[1]
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,200}',key_id) or not self.client: raise ValueError('Invalid public key identifier')
        url=f'https://api.smartthings.com/webhook/publicKey/{key_id}'
        if urlparse(url).hostname!='api.smartthings.com': raise ValueError('Disallowed key source')
        payload,_=await self.client.json('GET',url); material=payload.get('publicKey') if isinstance(payload,dict) else payload
        if not isinstance(material,str): raise ValueError('Invalid public key')
        key=serialization.load_pem_public_key(material.encode()); self.keys[key_id]=(time.time()+3600,key); return key
    async def verify(self,method,path,headers,body):
        fields,signed=self._auth(headers.get('authorization') or headers.get('Authorization')); digest=headers.get('digest') or headers.get('Digest'); date=headers.get('date') or headers.get('Date')
        if not digest or not date or not __import__('hmac').compare_digest(digest_value(body),digest): raise ValueError('Digest mismatch')
        try: parsed=datetime.strptime(date,'%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)
        except ValueError: raise ValueError('Invalid Date header') from None
        if abs((datetime.now(timezone.utc)-parsed).total_seconds())>self.skew: raise ValueError('Stale webhook request')
        values={'(request-target)':f'{method.lower()} {path}','digest':digest,'date':date}; signing='\n'.join(f'{name}: {values[name]}' for name in signed)
        try: (await self._key(fields['keyId'])).verify(base64.b64decode(fields['signature']),signing.encode(),padding.PKCS1v15(),hashes.SHA256())
        except Exception: raise ValueError('Invalid webhook signature') from None
        return fields['keyId']

class SwitchCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')

class LevelCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    level: int = Field(ge=0,le=100)

class SmartThingsProvider(Provider):
    info=ProviderInfo('smartthings','SmartThings',capabilities={'devices':True,'events':True,'commands':True,'webhooks':True},description='SmartThings devices, state and safe commands',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'client_id':{'type':'string'},'redirect_uri':{'type':'string'},'interval':{'type':'integer','minimum':60}},'additionalProperties':False},config_flow={'type':'oauth','credential_kinds':['client_secret'],'scopes':['r:devices:*','x:devices:*'],'fields':[{'name':'client_id','type':'text','required':True},{'name':'redirect_uri','type':'text','required':True},{'name':'interval','type':'duration'}]})
    def __init__(self,client=None):
        self.context=None; self.client=client or ProviderHTTP(timeout=15); self.task=None; self.devices={}; self.entities={}; self.last=None; self.last_error=None; self.unsupported=0; self.commands=0; self.verifier=SmartThingsRequestVerifier(self.client); self.subscription_status='unknown'; self.subscription_count=0; self.verified_webhooks=0; self.webhook_failures=0; self.event_ids=[]
        self.guard=WebhookGuard('smartthings')

    async def setup(self,context):
        self.context=context
        await context.service('switch','turn_on',SwitchCommand,self.turn_on,target_required=True,target_domains=('switch',))
        await context.service('switch','turn_off',SwitchCommand,self.turn_off,target_required=True,target_domains=('switch',))
        await context.service('light','set_level',LevelCommand,self.set_level,target_required=True,target_domains=('light',))

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

    async def _reconcile_subscriptions(self):
        state=await self.context.sync_state(); installed=state.get('installed_app_id')
        if not installed: self.subscription_status='not_configured'; return
        path=f'/installedapps/{installed}/subscriptions'; existing=(await self._json('GET',path)).get('items',[])
        desired={}
        for external,(_,device,component,capability,_,_) in self.entities.items():
            name=f'hcm-{self.context.instance_id}-{hashlib.sha1(external.encode()).hexdigest()[:12]}'
            attribute={'switch':'switch','switchLevel':'level','temperatureMeasurement':'temperature','relativeHumidityMeasurement':'humidity','contactSensor':'contact','motionSensor':'motion','presenceSensor':'presence','battery':'battery','washerOperatingState':'machineState','dryerOperatingState':'machineState','washerMachineState':'machineState','dryerMachineState':'machineState'}.get(capability)
            desired[name]={'name':name,'sourceType':'DEVICE','device':{'deviceId':device,'componentId':component,'capability':capability,'attribute':attribute,'stateChangeOnly':True}}
        by_name={x.get('name'):x for x in existing}; created=[]
        for name,payload in desired.items():
            if name not in by_name: created.append(await self._json('POST',path,json_body=payload))
        self.subscription_count=len(existing)+len(created); self.subscription_status='healthy'; state['subscriptions']=[x.get('id') or x.get('name') for x in list(existing)+created]; await self.context.save_sync_state(state)

    def _mapping(self,capability):
        return {'switch':('switch','state'),'switchLevel':('light','level'),'temperatureMeasurement':('sensor','temperature'),'relativeHumidityMeasurement':('sensor','humidity'),'contactSensor':('binary_sensor','contact'),'motionSensor':('binary_sensor','motion'),'presenceSensor':('device_tracker','presence'),'battery':('sensor','battery'),'washerOperatingState':('sensor','job_state'),'dryerOperatingState':('sensor','job_state'),'washerMachineState':('sensor','machine_state'),'dryerMachineState':('sensor','machine_state')}.get(capability)

    def _value(self,capability,attr):
        if not isinstance(attr,dict): return None
        value=attr.get('value')
        if capability in {'contactSensor','motionSensor','presenceSensor'}: return value
        if capability=='switchLevel' and isinstance(value,dict): return value.get('level')
        return value

    async def discover(self):
        sync=await self.context.sync_state(); sync.update({k:self.context.config.get(k) for k in ('installed_app_id','location_id') if self.context.config.get(k)}); await self.context.save_sync_state(sync)
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
        await self._reconcile_subscriptions()
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
        if capability=='switchLevel':
            level=max(0,min(100,int(value))); command={'component':component,'capability':'switchLevel','command':'setLevel','arguments':[level]}
        elif capability=='switch': command={'component':component,'capability':'switch','command':'on' if value=='on' else 'off'}
        else: raise ValueError('SmartThings capability is not commandable')
        result=await self._json('POST',f'/devices/{device}/commands',json_body={'commands':[command]})
        self.commands+=1; return {'accepted':True,'entity_id':entity_id,'device_id':device,'capability':capability,'result_id':result.get('requestId') if isinstance(result,dict) else None}
    async def turn_on(self,args,target): return await self.command(target,'on')
    async def turn_off(self,args,target): return await self.command(target,'off')
    async def set_level(self,args,target): return await self.command(target,max(0,min(100,args.level)))

    async def process_event(self,event):
        lifecycle_data=event.get('installedApp') or event.get('installData') or event.get('data',{})
        if lifecycle_data.get('installedAppId') or lifecycle_data.get('locationId'):
            state=await self.context.sync_state(); state.update({k:lifecycle_data[k] for k in ('installedAppId','locationId') if k in lifecycle_data}); state['installed_app_id']=state.pop('installedAppId',state.get('installed_app_id')); state['location_id']=state.pop('locationId',state.get('location_id')); await self.context.save_sync_state(state)
        event_id=event.get('eventId') or event.get('id')
        if event_id and event_id in self.event_ids: return {'accepted':True,'duplicate':True}
        if event_id: self.event_ids=(self.event_ids+[event_id])[-1000:]
        data=event.get('deviceEventData',event.get('data',{})); device=data.get('deviceId') or event.get('deviceId'); event_type=event.get('eventType')
        if event_type=='DEVICE_HEALTH_EVENT' or data.get('healthState'):
            available=str(data.get('healthState','')).upper() in {'ONLINE','AVAILABLE'}
            for row in self.entities.values():
                if row[1]==device: await self.context.availability(row[0],available)
            await self.context.emit('smartthings.device_online' if available else 'smartthings.device_offline',{'device_id':device}); return {'accepted':True,'device_id':device}
        capability=data.get('capability'); attribute=data.get('attribute'); value=data.get('value'); component=data.get('componentId','main')
        for row in self.entities.values():
            entity,external,comp,capability_id,domain,suffix=row
            if external==device and comp==component and capability_id==capability:
                normalized=self._value(capability,{'value':value}); await self.context.state(entity,normalized,attributes={'provider':'smartthings','capability':capability,'attribute':attribute,'event_id':event_id},available=True)
        return {'accepted':True,'device_id':device}

    async def handle_webhook(self,payload,signature,nonce,secret):
        self.guard.verify(payload,signature,secret,nonce); return await self.process_event(payload if isinstance(payload,dict) else {})
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
    async def diagnostics(self): return Diagnostics(counters={'devices':len(self.devices),'entities':len(self.entities),'unsupported_capabilities':self.unsupported,'commands':self.commands,'verified_webhooks':self.verified_webhooks,'verification_failures':self.webhook_failures,'subscriptions':self.subscription_count},checks={'account_connected':bool(self.context and self.context.account_ref),'webhook_ready':self.subscription_status in {'healthy','not_configured'}})

if 'smartthings' not in provider_factory.types: provider_factory.register_type('smartthings',SmartThingsProvider.info,lambda context:SmartThingsProvider())

webhook_router=APIRouter(prefix='/api/v1/integrations/smartthings',tags=['smartthings'])

@webhook_router.post('/webhook/{instance_id}')
async def smartthings_webhook(instance_id:str,request:Request):
    from .runtime import runtime
    provider=runtime.instances.get(instance_id)
    if not provider or not isinstance(provider.provider,SmartThingsProvider): raise HTTPException(404,'SmartThings instance not found')
    body=await request.body()
    if len(body)>1024*1024: raise HTTPException(413,'Webhook payload too large')
    try:
        await provider.provider.verifier.verify(request.method,request.url.path,dict(request.headers),body)
        payload=await request.json(); provider.provider.verified_webhooks+=1
        lifecycle=payload.get('lifecycle') or payload.get('eventType')
        if str(lifecycle).upper() in {'UNINSTALL','DELETE','DISCONNECT'}:
            await runtime.stop_instance(instance_id)
            async with db.acquire() as conn: await conn.execute("UPDATE integration_instances SET status='authentication_required',configured=false,last_error='SmartThings installation removed',updated_at=now() WHERE instance_id=$1",instance_id)
            if provider.provider.context.account_ref: await secret_store.revoke(provider.provider.context.account_ref)
            return {'accepted':True,'disconnected':True}
        result=await provider.provider.process_event(payload)
        state=await provider.provider.context.sync_state(); state['last_webhook_event']=payload.get('eventId') or payload.get('id'); await provider.provider.context.save_sync_state(state)
        return result
    except Exception as exc:
        provider.provider.webhook_failures+=1
        raise HTTPException(401,'Webhook verification failed') from None
