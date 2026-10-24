"""Shared Google OAuth-backed provider utilities and narrow Calendar/Gmail providers."""
import asyncio
import time
from datetime import datetime, timezone
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .oauth import OAuthHTTPClient, OAuthMetadata, refresh_scheduler
from . import secrets as secret_store
from .. import db
from .weather import record_poll

GOOGLE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'; GOOGLE_TOKEN='https://oauth2.googleapis.com/token'

class GoogleProvider(Provider):
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(timeout=15); self.task=None; self.last=None; self.updates=0
    async def _token(self):
        bundle=await self.context.account_credential()
        if isinstance(bundle,str): bundle={'access_token':bundle}
        expires=await self._expiry()
        if expires and expires-time.time() < 60 and bundle.get('refresh_token'):
            secret=await self.context.credential(); client_id=self.context.config.get('client_id')
            async def request(url,data,style): return (await self.client.json('POST',url,form_body=data,headers={'Accept':'application/json'}))[0]
            token=await OAuthHTTPClient(request).refresh(OAuthMetadata(GOOGLE_AUTH,GOOGLE_TOKEN),bundle['refresh_token'],client_id,secret)
            refreshed={'access_token':token.access_token,'refresh_token':token.refresh_token or bundle.get('refresh_token'),'token_type':token.token_type,'scopes':list(token.scopes)}
            ref=await secret_store.put(self.context.provider_id,'oauth_access_token',refreshed,metadata={'expires_at':token.expires_at})
            old=self.context.account_ref; self.context.account_ref=ref
            async with db.acquire() as conn: await conn.execute("UPDATE integration_instances SET account_ref=$2,last_success=now(),status='connected',last_error=NULL,updated_at=now() WHERE instance_id=$1",self.context.instance_id,ref)
            if old: await secret_store.revoke(old)
            bundle=refreshed
        return bundle['access_token']

    async def _expiry(self):
        if not self.context.account_ref: return None
        try: return (await secret_store.get_record(self.context.account_ref))['metadata'].get('expires_at')
        except Exception: return None

    async def google_json(self,url,**kwargs):
        token=await self._token(); headers={'Authorization':f'Bearer {token}'}; return (await self.client.json('GET',url,headers=headers,**kwargs))[0]
    async def schedule_refresh(self):
        if not self.context or not self.context.instance_id: return
        expiry=await self._expiry()
        if expiry and self.context.account_ref:
            refresh_scheduler.schedule(self.context.instance_id,self._token,max(1,expiry-time.time()-60))
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'account_connected':bool(self.context and self.context.account_ref)})

class GoogleCalendarProvider(GoogleProvider):
    info=ProviderInfo('google_calendar','Google Calendar',capabilities={'calendar':True,'events':True},description='Google Calendar events and upcoming schedule',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'client_id':{'type':'string'},'redirect_uri':{'type':'string'},'calendar_ids':{'type':'array','items':{'type':'string'}},'interval':{'type':'integer','minimum':60}},'additionalProperties':False},config_flow={'type':'oauth','credential_kinds':['client_secret'],'scopes':['https://www.googleapis.com/auth/calendar.readonly'],'fields':[{'name':'client_id','type':'text','required':True},{'name':'redirect_uri','type':'text'},{'name':'calendar_ids','type':'multi-select'},{'name':'interval','type':'duration'}]})
    async def setup(self,context):
        self.context=context; self.lifecycle={}; self.device=await context.device('calendar','Google Calendar',available=False); self.entity=await context.entity('calendar','calendar.events',self.device,'Google Calendar')
    def normalize_event(self,item):
        start=item.get('start',{}); end=item.get('end',{}); return {'event_id':item.get('id'),'summary':item.get('summary'),'description':item.get('description'),'location':item.get('location'),'start':start.get('dateTime') or start.get('date'),'end':end.get('dateTime') or end.get('date'),'all_day':bool(start.get('date')),'status':item.get('status'),'updated':item.get('updated')}
    def _when(self,value,all_day=False):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() if all_day else datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    async def _schedule(self,event):
        old=self.lifecycle.pop(event['event_id'],None)
        if old: old.cancel()
        start=self._when(event['start'],event['all_day']); end=self._when(event['end'],event['all_day'])
        async def run():
            try:
                if start>time.time(): await asyncio.sleep(start-time.time())
                await self.context.emit('google_calendar.event_started',event)
                if end>time.time(): await asyncio.sleep(end-time.time())
                await self.context.emit('google_calendar.event_ended',event)
            except asyncio.CancelledError: raise
        self.lifecycle[event['event_id']]=asyncio.create_task(run())
    async def poll(self):
        cfg=self.context.config; ids=cfg.get('calendar_ids') or ['primary']; events=[]
        for calendar_id in ids:
            data=await self.google_json(f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events',params={'singleEvents':'true','maxResults':'50','orderBy':'startTime','timeMin':'1970-01-01T00:00:00Z'}); events.extend(self.normalize_event(x) for x in data.get('items',[]) if x.get('status')!='cancelled')
        prior=await self.context.sync_state(); old=prior.get('events',{}); current={e.get('event_id'):e for e in events if e.get('event_id')}
        for event_id,event in current.items():
            if event_id not in old or old[event_id]!=event: await self.context.emit('google_calendar.event_updated',event)
        for event_id in set(old)-set(current): await self.context.emit('google_calendar.event_cancelled',{'event_id':event_id})
        for event_id,event in current.items():
            if event_id not in old or old[event_id]!=event: await self._schedule(event)
        await self.context.save_sync_state({'events':current}); await self.context.state(self.entity,{'events':events[:50],'next_event':events[0] if events else None},attributes={'provider':'google_calendar'}); await self.context.device('calendar','Google Calendar',available=True); self.last=events; self.updates+=1; await record_poll(self.context,True)
    async def start(self): await self.poll(); await self.schedule_refresh(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',300))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def reload(self): await self.stop(); self.client=ProviderHTTP(timeout=15); await self.start()
    async def stop(self):
        for task in getattr(self,'lifecycle',{}).values(): task.cancel()
        if getattr(self,'lifecycle',{}): await asyncio.gather(*self.lifecycle.values(),return_exceptions=True)
        self.lifecycle={}; await super().stop()

class GmailProvider(GoogleProvider):
    info=ProviderInfo('gmail','Gmail',capabilities={'mail':True,'events':True},description='Gmail unread state and new-message events',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'client_id':{'type':'string'},'redirect_uri':{'type':'string'},'interval':{'type':'integer','minimum':60}},'additionalProperties':False},config_flow={'type':'oauth','credential_kinds':['client_secret'],'scopes':['https://www.googleapis.com/auth/gmail.metadata'],'fields':[{'name':'client_id','type':'text','required':True},{'name':'redirect_uri','type':'text'},{'name':'interval','type':'duration'}]})
    async def setup(self,context):
        self.context=context; self.device=await context.device('mailbox','Gmail',available=False); self.entity=await context.entity('mail','sensor.unread_count',self.device,'Unread Mail')
    async def poll(self):
        sync=await self.context.sync_state(); data=await self.google_json('https://gmail.googleapis.com/gmail/v1/users/me/messages',params={'q':'is:unread','maxResults':'50'}); messages=data.get('messages',[]); await self.context.state(self.entity,len(messages),attributes={'provider':'gmail','sync_count':len(messages)}); await self.context.device('mailbox','Gmail',available=True)
        if not sync.get('baseline') or not sync.get('history_id'):
            sync.update({'baseline':True,'history_id':data.get('historyId'),'seen_ids':list({m.get('id') for m in messages if m.get('id')})}); await self.context.save_sync_state(sync); self.last=len(messages); self.updates+=1; return await record_poll(self.context,True)
        try: history=await self.google_json('https://gmail.googleapis.com/gmail/v1/users/me/history',params={'startHistoryId':sync['history_id'],'historyTypes':'messageAdded'})
        except Exception as exc:
            if getattr(exc,'status_code',None) in {400,404} or getattr(exc,'category',None)=='provider_error': sync.update({'baseline':False,'history_id':None}); await self.context.save_sync_state(sync); return await record_poll(self.context,True)
            raise
        seen=set(sync.get('seen_ids',[]))
        for record in history.get('history',[]):
            for item in record.get('messagesAdded',[]):
                msg=item.get('message',{}); mid=msg.get('id')
                if not mid or mid in seen: continue
                seen.add(mid); detail=await self.google_json(f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}',params={'format':'metadata'})
                await self.context.emit('gmail.message_received',{'message_id':mid,'thread_id':msg.get('threadId'),'metadata':detail.get('payload',{}).get('headers',[])})
        sync.update({'history_id':history.get('historyId',sync['history_id']),'seen_ids':list(seen)[-5000:]}); await self.context.save_sync_state(sync); self.last=len(messages); self.updates+=1; await record_poll(self.context,True)
    async def start(self): await self.poll(); await self.schedule_refresh(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',300))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def reload(self): await self.stop(); self.client=ProviderHTTP(timeout=15); await self.start()

for _id,_provider in (('google_calendar',GoogleCalendarProvider),('gmail',GmailProvider)):
    if _id not in provider_factory.types: provider_factory.register_type(_id,_provider.info,lambda context,p=_provider:p())
