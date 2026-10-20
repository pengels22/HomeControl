"""Shared Google OAuth-backed provider utilities and narrow Calendar/Gmail providers."""
import asyncio
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .weather import record_poll

GOOGLE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'; GOOGLE_TOKEN='https://oauth2.googleapis.com/token'

class GoogleProvider(Provider):
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(timeout=15); self.task=None; self.last=None; self.updates=0
    async def google_json(self,url,**kwargs):
        token=await self.context.credential(); headers={'Authorization':f'Bearer {token}'}; return (await self.client.json('GET',url,headers=headers,**kwargs))[0]
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'account_connected':bool(self.context and self.context.credential_ref)})

class GoogleCalendarProvider(GoogleProvider):
    info=ProviderInfo('google_calendar','Google Calendar',capabilities={'calendar':True,'events':True},description='Google Calendar events and upcoming schedule',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'calendar_ids':{'type':'array','items':{'type':'string'}},'interval':{'type':'integer','minimum':60}},'additionalProperties':False},config_flow={'type':'oauth','fields':[{'name':'calendar_ids','type':'multi-select'},{'name':'interval','type':'duration'}]})
    async def setup(self,context):
        self.context=context; self.device=await context.device('calendar','Google Calendar',available=False); self.entity=await context.entity('calendar','calendar.events',self.device,'Google Calendar')
    def normalize_event(self,item):
        start=item.get('start',{}); end=item.get('end',{}); return {'event_id':item.get('id'),'summary':item.get('summary'),'description':item.get('description'),'location':item.get('location'),'start':start.get('dateTime') or start.get('date'),'end':end.get('dateTime') or end.get('date'),'all_day':bool(start.get('date')),'status':item.get('status'),'updated':item.get('updated')}
    async def poll(self):
        cfg=self.context.config; ids=cfg.get('calendar_ids') or ['primary']; events=[]
        for calendar_id in ids:
            data=await self.google_json(f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events',params={'singleEvents':'true','maxResults':'50','orderBy':'startTime','timeMin':'1970-01-01T00:00:00Z'}); events.extend(self.normalize_event(x) for x in data.get('items',[]) if x.get('status')!='cancelled')
        await self.context.state(self.entity,{'events':events[:50],'next_event':events[0] if events else None},attributes={'provider':'google_calendar'}); await self.context.device('calendar','Google Calendar',available=True); self.last=events; self.updates+=1; await record_poll(self.context,True)
    async def start(self): await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',300))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def reload(self): await self.stop(); self.client=ProviderHTTP(timeout=15); await self.start()

class GmailProvider(GoogleProvider):
    info=ProviderInfo('gmail','Gmail',capabilities={'mail':True,'events':True},description='Gmail unread state and new-message events',setup_type='oauth',supports_multiple=True,config_schema={'type':'object','properties':{'interval':{'type':'integer','minimum':60}},'additionalProperties':False},config_flow={'type':'oauth','fields':[{'name':'interval','type':'duration'}]})
    async def setup(self,context):
        self.context=context; self.device=await context.device('mailbox','Gmail',available=False); self.entity=await context.entity('mail','sensor.unread_count',self.device,'Unread Mail')
    async def poll(self):
        data=await self.google_json('https://gmail.googleapis.com/gmail/v1/users/me/messages',params={'q':'is:unread','maxResults':'50'}); messages=data.get('messages',[]); await self.context.state(self.entity,len(messages),attributes={'provider':'gmail','sync_count':len(messages)}); await self.context.device('mailbox','Gmail',available=True)
        previous=set(self.context.config.get('_seen_ids',[])); current={m.get('id') for m in messages if m.get('id')}
        for message_id in current-previous: await self.context.emit('gmail.message_received',{'message_id':message_id,'thread_id':next((m.get('threadId') for m in messages if m.get('id')==message_id),None)})
        self.context.config['_seen_ids']=list(current); self.last=len(messages); self.updates+=1; await record_poll(self.context,True)
    async def start(self): await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',300))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def reload(self): await self.stop(); self.client=ProviderHTTP(timeout=15); await self.start()

for _id,_provider in (('google_calendar',GoogleCalendarProvider),('gmail',GmailProvider)):
    if _id not in provider_factory.types: provider_factory.register_type(_id,_provider.info,lambda context,p=_provider:p())
