"""Provider-neutral durable automation engine.

The engine consumes the integration event log and resolves actions through the
existing service registry. It never calls provider handlers directly.
"""
from __future__ import annotations
import asyncio, json, re, hashlib, math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time, timezone, date
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from . import db
from .expressions import ExpressionEngine, ExpressionError, Snapshot, Undefined

MODES = {'single','restart','queued','parallel'}
STATUSES = {'running','success','failed','cancelled','skipped','HCM_RESTART'}
ERRORS = {'validation error','missing entity','unavailable target','service unavailable','service failure','timeout','cancelled','internal error'}
MAX_TRACE_STEPS = 200
MAX_TRACE_BYTES = 64_000

class AutomationValidationError(ValueError): pass
class AutomationStopped(Exception): pass


def trigger_id(trigger):
    """Stable identity for a schedule trigger, independent of actions/order."""
    body={k:v for k,v in trigger.items() if k not in {'id','trigger_id'}}
    return 'trg_' + hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

class SunUnavailable(Exception): pass

class SunCalculator:
    """Bounded NOAA sunrise/sunset calculation; no network or provider dependency."""
    def __init__(self, latitude, longitude, timezone_name='UTC'):
        if latitude is None or longitude is None: raise SunUnavailable('Location is not configured')
        if not -90 <= float(latitude) <= 90 or not -180 <= float(longitude) <= 180: raise SunUnavailable('Location is invalid')
        self.latitude=float(latitude); self.longitude=float(longitude); self.timezone=ZoneInfo(timezone_name)
    def _event(self, day, rising):
        n=day.timetuple().tm_yday; lng=self.longitude/15.0; zenith=90.8333
        t=n+((6-lng)/24 if rising else (18-lng)/24)
        M=(0.9856*t)-3.289
        L=(M+1.916*math.sin(math.radians(M))+0.020*math.sin(math.radians(2*M))+282.634)%360
        ra=math.degrees(math.atan(0.91764*math.tan(math.radians(L)))%math.pi)
        ra=(ra+360)%360; lq=(math.floor(L/90))*90; rq=(math.floor(ra/90))*90; ra=(ra+(lq-rq))/15
        sd=0.39782*math.sin(math.radians(L)); cd=math.cos(math.asin(sd))
        cosh=(math.cos(math.radians(zenith))-sd*math.sin(math.radians(self.latitude)))/(cd*math.cos(math.radians(self.latitude)))
        if cosh>1 or cosh < -1: raise SunUnavailable('Solar event unavailable at this latitude/date')
        h=(360-math.degrees(math.acos(cosh)) if rising else math.degrees(math.acos(cosh)))/15
        ut=(h+ra-0.06571*t-6.622-lng)%24
        utc=datetime.combine(day,dt_time(0),timezone.utc)+timedelta(hours=ut)
        local=utc.astimezone(self.timezone)
        if local.date() < day: local += timedelta(days=1)
        elif local.date() > day and rising: local -= timedelta(days=1)
        return local
    def events(self, day): return {'sunrise':self._event(day,True),'sunset':self._event(day,False)}



def _json(value):
    return json.loads(json.dumps(value, allow_nan=False))

def _safe(value):
    if isinstance(value, dict):
        blocked = ('token','secret','password','authorization','api_key','access_token','refresh_token')
        return {str(k): _safe(v) for k,v in value.items() if not any(x in str(k).lower() for x in blocked)}
    if isinstance(value, list): return [_safe(v) for v in value]
    return value

def _as_uuid(value):
    try: return UUID(str(value))
    except (ValueError, TypeError, AttributeError): return value

class AutomationStore:
    def __init__(self, *, timezone_name='UTC'):
        self.expressions=ExpressionEngine(timezone_name=timezone_name)
    async def _validate_expression_values(self, value):
        if isinstance(value,str) and ('{{' in value or value.strip()):
            # Literal strings are retained; template/native syntax is compiled only when explicitly marked.
            if '{{' in value: self.expressions.compile(value,syntax='jinja')
        elif isinstance(value,dict):
            for item in value.values(): await self._validate_expression_values(item)
        elif isinstance(value,list):
            for item in value: await self._validate_expression_values(item)
    async def _entity_ref(self, ref):
        if isinstance(ref, int) or (isinstance(ref,str) and ref.isdigit()): return int(ref)
        async with db.acquire() as conn:
            value = await conn.fetchval('SELECT id FROM entities WHERE entity_id=$1', str(ref))
        if value is None: raise AutomationValidationError(f'Unknown entity reference: {ref}')
        return int(value)

    async def validate(self, definition: dict[str,Any], *, existing_id=None):
        if not isinstance(definition,dict): raise AutomationValidationError('Automation must be an object')
        allowed={'name','description','enabled','mode','max_runs','triggers','trigger_definitions','conditions','condition','actions','action_sequence'}
        unknown=set(definition)-allowed
        if unknown: raise AutomationValidationError(f'Unsupported automation keys: {sorted(unknown)}')
        name=str(definition.get('name','')).strip()
        if not name: raise AutomationValidationError('Automation name is required')
        mode=definition.get('mode','single')
        if mode not in MODES: raise AutomationValidationError('Invalid automation mode')
        max_runs=int(definition.get('max_runs',10))
        if not 1 <= max_runs <= 10: raise AutomationValidationError('max_runs must be between 1 and 10')
        triggers=definition.get('triggers',definition.get('trigger_definitions'))
        actions=definition.get('actions',definition.get('action_sequence'))
        if not isinstance(triggers,list) or not triggers: raise AutomationValidationError('At least one trigger is required')
        if not isinstance(actions,list): raise AutomationValidationError('Actions must be a list')
        normalized=[]
        for trigger in triggers: normalized.append(await self._validate_trigger(trigger))
        conditions=definition.get('conditions',definition.get('condition'))
        if conditions is not None: await self._validate_condition(conditions)
        for action in actions: await self._validate_action(action)
        return {'name':name,'description':definition.get('description'),'enabled':bool(definition.get('enabled',True)),'mode':mode,'max_runs':max_runs,'triggers':normalized,'conditions':conditions,'actions':actions}

    def _offset_seconds(self, value):
        if isinstance(value,(int,float)): return int(value)
        if value is None: return 0
        text=str(value); sign=-1 if text.startswith('-') else 1; text=text.lstrip('+-')
        parts=text.split(':')
        if len(parts) not in (2,3): raise AutomationValidationError('Invalid sun offset')
        try: nums=[int(x) for x in parts]
        except ValueError: raise AutomationValidationError('Invalid sun offset')
        if len(nums)==2: nums=[0,*nums]
        if nums[1]>59 or nums[2]>59: raise AutomationValidationError('Invalid sun offset')
        return sign*(nums[0]*3600+nums[1]*60+nums[2])

    async def _validate_trigger(self,t):
        if not isinstance(t,dict) or set(t)-{'type','entity_ref','from','to','attribute','for','event_type','provider_id','instance_id','device_ref','payload','times','time','every_minutes','every_hours','minute','hour','sun','offset'}: raise AutomationValidationError('Invalid trigger definition')
        typ=t.get('type')
        if typ=='state':
            if 'entity_ref' not in t: raise AutomationValidationError('State trigger needs entity_ref')
            t=dict(t); t['entity_ref']=await self._entity_ref(t['entity_ref'])
            if 'for' in t and (not isinstance(t['for'],(int,float)) or t['for']<0): raise AutomationValidationError('for must be non-negative seconds')
        elif typ=='event':
            if not isinstance(t.get('event_type'),str) or not t['event_type']: raise AutomationValidationError('Event trigger needs event_type')
        elif typ=='time':
            times=t.get('times', [t.get('time')] if t.get('time') else [])
            if not times or any(not re.fullmatch(r'\d{2}:\d{2}(:\d{2})?',str(v)) for v in times): raise AutomationValidationError('Time trigger needs HH:MM times')
        elif typ=='time_pattern':
            if not any(k in t for k in ('every_minutes','every_hours','minute','hour')): raise AutomationValidationError('Time pattern needs a pattern')
        elif typ=='sun':
            if t.get('sun') not in ('sunrise','sunset'): raise AutomationValidationError('Sun trigger needs sunrise or sunset')
            t=dict(t); t['offset_seconds']=self._offset_seconds(t.get('offset',0)); identity=dict(t); identity.pop('offset',None); t['trigger_id']=trigger_id(identity)
        else: raise AutomationValidationError('Unsupported trigger type')
        if typ in ('time','time_pattern'):
            t=dict(t); t['trigger_id']=trigger_id(t)
        return t

    async def _validate_condition(self,c):
        if not isinstance(c,dict): raise AutomationValidationError('Condition must be an object')
        typ=c.get('type')
        if typ in ('and','or'):
            if not isinstance(c.get('conditions'),list): raise AutomationValidationError('Boolean condition needs conditions')
            for child in c['conditions']: await self._validate_condition(child)
        elif typ=='not': await self._validate_condition(c.get('condition'))
        elif typ=='template':
            expression=c.get('expression')
            if not isinstance(expression,str): raise AutomationValidationError('Template condition needs expression')
            try: self.expressions.compile(expression,syntax='jinja' if '{{' in expression else 'native')
            except ExpressionError as exc: raise AutomationValidationError(f'Expression {exc.category}: {exc}') from None
        elif typ=='state':
            c['entity_ref']=await self._entity_ref(c.get('entity_ref'))
            if 'state' not in c: raise AutomationValidationError('State condition needs state')
        elif typ=='numeric_state':
            c['entity_ref']=await self._entity_ref(c.get('entity_ref'))
            if c.get('above') is None and c.get('below') is None: raise AutomationValidationError('Numeric condition needs above or below')
            for k in ('above','below'):
                if k in c and c[k] is not None:
                    try: float(c[k])
                    except (TypeError,ValueError): raise AutomationValidationError(f'{k} must be numeric')
        elif typ=='time':
            if not c.get('after') and not c.get('before'): raise AutomationValidationError('Time condition needs after or before')
        else: raise AutomationValidationError('Unsupported condition type')

    async def _validate_action(self,a):
        if not isinstance(a,dict): raise AutomationValidationError('Action must be an object')
        typ=a.get('type')
        if typ=='service':
            if not isinstance(a.get('domain'),str) or not isinstance(a.get('service'),str): raise AutomationValidationError('Service action needs domain and service')
            if 'target_entity_ref' in a: a['target_entity_ref']=await self._entity_ref(a['target_entity_ref'])
            await self._validate_expression_values(a.get('service_data',{}))
            if a.get('response_variable') is not None and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',str(a['response_variable'])): raise AutomationValidationError('Invalid response variable')
        elif typ=='variables':
            if not isinstance(a.get('variables'),dict): raise AutomationValidationError('Variables action needs a mapping')
            for name,value in a['variables'].items():
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',str(name)): raise AutomationValidationError('Invalid variable name')
                await self._validate_expression_values(value)
        elif typ=='delay':
            if float(a.get('seconds',-1))<0 or float(a.get('seconds',0))>86400: raise AutomationValidationError('Delay must be 0..86400 seconds')
        elif typ=='condition': await self._validate_condition(a.get('condition'))
        elif typ=='stop': pass
        else: raise AutomationValidationError('Unsupported action type')

    async def create(self, definition):
        data=await self.validate(definition)
        async with db.acquire() as conn:
            row=await conn.fetchrow('''INSERT INTO automations(name,description,enabled,mode,max_runs,trigger_definitions,condition_definition,action_sequence) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb) RETURNING *''',data['name'],data['description'],data['enabled'],data['mode'],data['max_runs'],json.dumps(data['triggers']),json.dumps(data['conditions']) if data['conditions'] is not None else None,json.dumps(data['actions']))
        return dict(row)

    async def update(self, automation_id, definition):
        data=await self.validate(definition,existing_id=automation_id)
        async with db.acquire() as conn:
            row=await conn.fetchrow('''UPDATE automations SET name=$2,description=$3,enabled=$4,mode=$5,max_runs=$6,trigger_definitions=$7::jsonb,condition_definition=$8::jsonb,action_sequence=$9::jsonb,revision=revision+1,updated_at=now() WHERE automation_id=$1 RETURNING *''',_as_uuid(automation_id),data['name'],data['description'],data['enabled'],data['mode'],data['max_runs'],json.dumps(data['triggers']),json.dumps(data['conditions']) if data['conditions'] is not None else None,json.dumps(data['actions']))
        if not row: raise LookupError('Automation not found')
        return dict(row)

    async def get(self, automation_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM automations WHERE automation_id=$1',_as_uuid(automation_id))
        if not row: raise LookupError('Automation not found')
        return dict(row)
    async def list(self):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT * FROM automations ORDER BY name,automation_id')
        return [dict(r) for r in rows]
    async def set_enabled(self, automation_id, enabled):
        async with db.acquire() as conn: row=await conn.fetchrow('UPDATE automations SET enabled=$2,updated_at=now() WHERE automation_id=$1 RETURNING *',_as_uuid(automation_id),enabled)
        if not row: raise LookupError('Automation not found')
        return dict(row)
    async def delete(self, automation_id):
        async with db.acquire() as conn: result=await conn.execute('DELETE FROM automations WHERE automation_id=$1',_as_uuid(automation_id))
        return result.endswith('1')

@dataclass
class RunContext:
    automation: dict
    run_id: UUID
    trace: list
    cancelled: asyncio.Event
    dry_run: bool=False
    variables: dict=None
    trigger: dict=None

class AutomationEngine:
    def __init__(self, registry, *, timezone_name='UTC', latitude=None, longitude=None, store=None):
        self.registry=registry; self.store=store or AutomationStore(); self.timezone=ZoneInfo(timezone_name)
        self.sun=SunCalculator(latitude,longitude,timezone_name) if latitude is not None and longitude is not None else None
        self.expressions=ExpressionEngine(timezone_name=timezone_name)
        self.active=defaultdict(dict); self.queues=defaultdict(deque); self.timers={}; self.tasks=set(); self.task=None; self.wake=asyncio.Event(); self.scheduler_started_at=None

    async def start(self):
        async with db.acquire() as conn:
            await conn.execute("UPDATE automation_runs SET status='HCM_RESTART',ended_at=now(),result='HCM restart',error_category='cancelled' WHERE status='running'")
            self.cursor=int(await conn.fetchval("SELECT last_event_id FROM automation_engine_state WHERE state_key='integration_events'") or 0)
            previous=await conn.fetchval("SELECT last_seen_at FROM automation_scheduler_state WHERE state_key='scheduler'")
        self.scheduler_started_at=datetime.now(timezone.utc); await self.reconstruct_schedules(previous,self.scheduler_started_at)
        async with db.acquire() as conn: await conn.execute("UPDATE automation_scheduler_state SET last_seen_at=$1,updated_at=now() WHERE state_key='scheduler'",self.scheduler_started_at)
        if not self.task or self.task.done(): self.task=asyncio.create_task(self._loop())

    async def stop(self):
        for runs in self.active.values():
            for ctx in runs.values(): ctx.cancelled.set()
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True); self.task=None
        for task in list(self.timers.values()): task.cancel()
        for task in list(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks,return_exceptions=True)
        self.timers.clear(); self.tasks.clear()

    def notify(self): self.wake.set()
    async def cancel_automation(self, automation_id):
        aid=str(automation_id)
        for ctx in self.active.get(aid,{}).values(): ctx.cancelled.set()
        self.queues[aid].clear()
        for key,task in list(self.timers.items()):
            if key[0]==aid: task.cancel(); self.timers.pop(key,None)
        self.wake.set()

    async def update_automation(self, automation_id, definition):
        await self.cancel_automation(automation_id)
        return await self.store.update(automation_id,definition)

    async def set_enabled(self, automation_id, enabled):
        if not enabled: await self.cancel_automation(automation_id)
        return await self.store.set_enabled(automation_id,enabled)

    async def delete_automation(self, automation_id):
        await self.cancel_automation(automation_id)
        return await self.store.delete(automation_id)


    async def _loop(self):
        while True:
            try: await self.drain_once(); await self.schedule_tick(); await asyncio.wait_for(self.wake.wait(),timeout=1.0); self.wake.clear()
            except asyncio.TimeoutError: pass
            except asyncio.CancelledError: raise
            except Exception: await asyncio.sleep(.2)

    async def drain_once(self):
        events=await self.registry.events_after(self.cursor,limit=100)
        for event in events:
            event_id=int(event['event_id']); automations=await self.store.list()
            for automation in automations:
                if automation['enabled'] and any(self._trigger_matches(t,event,automation_id=str(automation['automation_id'])) for t in self._json_field(automation['trigger_definitions'])):
                    await self.trigger(automation,source='event',event=event)
            async with db.acquire() as conn: await conn.execute("UPDATE automation_engine_state SET last_event_id=$1,updated_at=now() WHERE state_key='integration_events'",event_id)
            self.cursor=event_id
        return len(events)

    def _json_field(self,v): return json.loads(v) if isinstance(v,str) else (v or [])
    def _trigger_matches(self,t,e,automation_id=None):
        typ=t.get('type'); payload=e.get('payload') or {}
        if typ=='event':
            if e.get('event_type')!=t.get('event_type'): return False
            for k in ('provider_id','instance_id'):
                if t.get(k) is not None and str(e.get(k))!=str(t[k]): return False
            if t.get('entity_ref') is not None and int(e.get('entity_id') or -1)!=int(t['entity_ref']): return False
            return all(payload.get(k)==v for k,v in (t.get('payload') or {}).items())
        if typ=='state':
            if int(e.get('entity_id') or -1)!=int(t.get('entity_ref')) or e.get('event_type')!='entity.state_changed': return False
            current=payload.get('attributes',{}).get(t['attribute']) if t.get('attribute') else payload.get('state')
            previous=(payload.get('previous_state') if 'previous_state' in payload else None)
            if t.get('from') is not None and previous!=t['from']: return False
            if t.get('to') is not None and current!=t['to']: return False
            if t.get('from') is None and t.get('to') is None and previous==current: return False
            if t.get('for'):
                key=(str(automation_id or ''),t.get('trigger_id') or trigger_id(t),str(t.get('entity_ref'))); self._start_timer(key,t,e,current)
                return False
            return True
        return False

    def _start_timer(self,key,t,event,current):
        if key in self.timers: return
        async def delayed():
            try:
                await asyncio.sleep(float(t['for']))
                async with db.acquire() as conn:
                    row=await conn.fetchrow('SELECT state,attributes FROM entities WHERE id=$1 AND enabled',int(t['entity_ref']))
                if row:
                    current=(row['attributes'] or {}).get(t['attribute']) if t.get('attribute') else row['state']
                    still_matches=t.get('to') is None or current==t.get('to')
                    for automation in await self.store.list():
                        if still_matches and automation['enabled'] and t in self._json_field(automation['trigger_definitions']): await self.trigger(automation,source='event',event=event)
            except asyncio.CancelledError: pass
            finally: self.timers.pop(key,None)
        task=asyncio.create_task(delayed()); self.timers[key]=task; self.tasks.add(task); task.add_done_callback(self.tasks.discard)

    def _valid_local(self, value):
        # Skip nonexistent spring-forward wall times; choose fold=0 on fall-back.
        candidate=value.replace(fold=0)
        back=candidate.astimezone(timezone.utc).astimezone(self.timezone)
        return back.replace(tzinfo=None)==value.replace(tzinfo=None)

    def _day_occurrences(self, trigger, day):
        typ=trigger.get('type'); values=[]
        if typ=='time':
            raw=trigger.get('times',[trigger.get('time')])
            for item in raw:
                local=datetime.combine(day,dt_time.fromisoformat(str(item)),self.timezone)
                if self._valid_local(local): values.append(local)
        elif typ=='time_pattern':
            for minute in range(1440):
                local=datetime.combine(day,dt_time(minute//60,minute%60),self.timezone)
                ok=True
                if trigger.get('every_minutes'): ok &= minute % int(trigger['every_minutes'])==0
                if trigger.get('every_hours'): ok &= minute%60==0 and (minute//60)%int(trigger['every_hours'])==0
                if trigger.get('minute') is not None: ok &= local.minute==int(trigger['minute'])
                if trigger.get('hour') is not None: ok &= local.hour==int(trigger['hour'])
                if ok and self._valid_local(local): values.append(local)
        elif typ=='sun' and self.sun:
            try: values.append(self.sun.events(day)[trigger['sun']]+timedelta(seconds=int(trigger.get('offset_seconds',0))))
            except SunUnavailable: pass
        return values

    def _latest_occurrence(self, trigger, now):
        candidates=[]
        for delta in (0,1): candidates.extend(self._day_occurrences(trigger,(now-timedelta(days=delta)).date()))
        old=[x for x in candidates if x<=now]
        return max(old) if old else None

    async def _record_occurrence(self, automation, trigger, intended, *, catch_up=False, skipped=False, reason=None):
        tid=trigger.get('trigger_id') or trigger_id(trigger); status='skipped' if skipped else 'scheduled'
        async with db.acquire() as conn:
            row=await conn.fetchrow("""INSERT INTO automation_schedule_ledger(automation_id,trigger_id,trigger_key,intended_fire_at,status,catch_up,reason) VALUES($1,$2,$2,$3,$4,$5,$6) ON CONFLICT(automation_id,trigger_id,intended_fire_at) DO NOTHING RETURNING occurrence_id""",_as_uuid(automation['automation_id']),tid,intended.astimezone(timezone.utc),status,catch_up,reason)
        if not row or skipped: return False
        context={'trigger_type':trigger.get('type'),'trigger_id':tid,'intended_fire_at':intended.isoformat(),'actual_invocation_at':datetime.now(self.timezone).isoformat(),'catch_up':catch_up}
        run_id=await self.trigger(automation,source='schedule',event=None,schedule=context)
        final='executed' if run_id else 'skipped'
        async with db.acquire() as conn: await conn.execute("UPDATE automation_schedule_ledger SET status=$2,actual_fire_at=now(),reason=$3 WHERE occurrence_id=$1",row['occurrence_id'],final,'run limit' if not run_id else None)
        return bool(run_id)

    async def reconstruct_schedules(self, previous, now):
        automations=await self.store.list(); previous=previous.astimezone(self.timezone) if previous else now
        for automation in automations:
            if not automation['enabled']: continue
            for trigger in self._json_field(automation['trigger_definitions']):
                if trigger.get('type') not in ('time','time_pattern','sun'): continue
                latest=self._latest_occurrence(trigger,now)
                if latest is None or latest<=previous: continue
                if now-latest<=timedelta(hours=24): await self._record_occurrence(automation,trigger,latest,catch_up=True)
                else: await self._record_occurrence(automation,trigger,latest,skipped=True,reason='older than 24 hours')

    async def schedule_tick(self, now=None):
        now = now or datetime.now(self.timezone)
        for automation in await self.store.list():
            if not automation['enabled']: continue
            for trigger in self._json_field(automation['trigger_definitions']):
                if trigger.get('type') not in ('time','time_pattern','sun'): continue
                for intended in self._day_occurrences(trigger,now.date()):
                    if abs((intended-now).total_seconds()) < 30: await self._record_occurrence(automation,trigger,intended)

    async def catch_up_schedules(self, since, now=None):
        now=now or datetime.now(self.timezone)
        await self.reconstruct_schedules(since,now)

    async def trigger(self,automation,*,source='manual',event=None,dry_run=False,schedule=None):
        aid=str(automation['automation_id']); mode=automation['mode']; active=self.active[aid]
        if mode=='single' and active: return None
        if mode=='restart' and active:
            for ctx in active.values(): ctx.cancelled.set()
        if mode=='queued' and len(active)+len(self.queues[aid])>=int(automation['max_runs']): return None
        if mode=='parallel' and len(active)>=int(automation['max_runs']): return None
        ctx=RunContext(automation,uuid4(),[],asyncio.Event(),dry_run,variables={},trigger={})
        if schedule: ctx.trigger={'trigger_id':schedule.get('trigger_id'),'trigger_type':schedule.get('trigger_type'),'intended_time':schedule.get('intended_fire_at'),'catch_up':schedule.get('catch_up',False),'offset':schedule.get('offset')}; ctx.trace.append({'step':'schedule_trigger',**_safe(schedule)})
        elif event:
            payload=_safe(event.get('payload') or {})
            ctx.trigger={'platform':'event','event_type':event.get('event_type'),'event_id':event.get('event_id'),'event':payload}
            if event.get('event_type')=='entity.state_changed':
                ctx.trigger.update({'platform':'state','entity_ref':event.get('entity_id'),'entity_id':event.get('entity_id'),'from_state':{'state':payload.get('previous_state')},'to_state':{'state':payload.get('state'),'attributes':payload.get('attributes',{}),'availability':payload.get('available',True)}})
        if mode=='queued' and active: self.queues[aid].append(ctx); return ctx.run_id
        active[str(ctx.run_id)]=ctx; task=asyncio.create_task(self._execute(ctx,source,event)); self.tasks.add(task); task.add_done_callback(self.tasks.discard); return ctx.run_id

    async def _execute(self,ctx,source,event):
        a=ctx.automation; started=datetime.now(timezone.utc); status='running'; result=None; category=None
        await self._persist_run(ctx,source,event,started,status)
        try:
            if a.get('condition_definition') and not await self.evaluate_condition(self._json_field(a['condition_definition']),ctx): status='skipped'; result='condition false'
            else:
                for action in self._json_field(a['action_sequence']):
                    await self._action(ctx,action)
                status='success'; result='completed'
        except AutomationStopped as exc: status='skipped'; result=str(exc)
        except asyncio.CancelledError: status='cancelled'; result='cancelled'; category='cancelled'
        except LookupError as exc: status='failed'; result=str(exc); category='missing entity'
        except PermissionError as exc: status='failed'; result=str(exc); category='service unavailable'
        except Exception as exc: status='failed'; result=f'{type(exc).__name__}'; category='internal error'
        finally:
            await self._finish_run(ctx,status,result,category,started)
            self.active[str(a['automation_id'])].pop(str(ctx.run_id),None)
            if self.queues[str(a['automation_id'])]:
                nxt=self.queues[str(a['automation_id'])].popleft(); self.active[str(a['automation_id'])][str(nxt.run_id)]=nxt; task=asyncio.create_task(self._execute(nxt,'schedule',None)); self.tasks.add(task); task.add_done_callback(self.tasks.discard)

    async def _persist_run(self,ctx,source,event,started,status):
        async with db.acquire() as conn: await conn.execute('INSERT INTO automation_runs(run_id,automation_id,trigger_source,trigger_event_id,started_at,status,mode,trace) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)',ctx.run_id,_as_uuid(ctx.automation['automation_id']),source,(event or {}).get('event_id'),started,status,ctx.automation['mode'],json.dumps(ctx.trace))
    async def _finish_run(self,ctx,status,result,category,started):
        trace=_safe(ctx.trace)[-MAX_TRACE_STEPS:]
        while trace and len(json.dumps(trace))>MAX_TRACE_BYTES: trace.pop(0)
        raw=json.dumps(trace)
        async with db.acquire() as conn:
            await conn.execute('UPDATE automation_runs SET ended_at=now(),status=$2,result=$3,error_category=$4,trace=$5::jsonb WHERE run_id=$1',ctx.run_id,status,result,category,raw)
            await conn.execute('UPDATE automations SET last_triggered_at=CASE WHEN $2 IN (\'success\',\'failed\',\'skipped\') THEN now() ELSE last_triggered_at END,last_run_status=$2 WHERE automation_id=$1',_as_uuid(ctx.automation['automation_id']),status)

    async def _action(self,ctx,a):
        if ctx.cancelled.is_set(): raise asyncio.CancelledError
        typ=a['type']; begin=datetime.now(timezone.utc); ctx.trace.append({'step':'action_start','type':typ,'at':begin.isoformat()})
        if typ=='delay':
            if not ctx.dry_run:
                try:
                    await asyncio.wait_for(ctx.cancelled.wait(), timeout=float(a['seconds']))
                    raise asyncio.CancelledError
                except asyncio.TimeoutError:
                    pass
        elif typ=='condition':
            if not await self.evaluate_condition(a['condition'],ctx): raise AutomationStopped('condition action false')
        elif typ=='variables':
            for name,value in a['variables'].items(): ctx.variables[name]=await self._resolve_value(value,ctx)
        elif typ=='stop': raise AutomationStopped(a.get('reason','stopped'))
        elif typ=='service':
            provider_id=a.get('provider_id')
            if provider_id is None and a.get('target_entity_ref') is not None:
                async with db.acquire() as conn: provider_id=await conn.fetchval('SELECT provider_id FROM entities WHERE id=$1',int(a['target_entity_ref']))
            declarations=await self.registry.services.inspect(provider_id)
            declaration=next((x for x in declarations if x['domain']==a['domain'] and x['service_name']==a['service']),{})
            arguments=await self._resolve_value(a.get('service_data',{}),ctx)
            ctx.trace.append({'step':'service','domain':a['domain'],'service':a['service'],'target':a.get('target_entity_ref'),'arguments':_safe(arguments),'physical_mutation':bool(declaration.get('mutates_physical_state',False))})
            result=None
            if not ctx.dry_run:
                if not provider_id: raise LookupError('Service provider unavailable')
                result=await self.registry.services.invoke(provider_id,a['domain'],a['service'],arguments,target_entity_id=a.get('target_entity_ref'),instance_id=a.get('instance_id'))
            if a.get('response_variable'): ctx.variables[a['response_variable']]=result if result is not None else Undefined
        ctx.trace.append({'step':'action_end','type':typ,'at':datetime.now(timezone.utc).isoformat()})

    def _expression_context(self,ctx):
        return {'trigger':ctx.trigger if ctx else {},'variables':ctx.variables if ctx else {},'run':{'id':str(ctx.run_id)} if ctx else {},'event':(ctx.trigger or {}).get('event',{}) if ctx else {}}

    async def _resolve_value(self,value,ctx):
        if isinstance(value,str) and '{{' in value:
            started=datetime.now(timezone.utc)
            result=await self.expressions.evaluate(value,context=self._expression_context(ctx),syntax='jinja')
            ctx.trace.append({'step':'expression','source_id':hashlib.sha256(value.encode()).hexdigest()[:16],'result_type':type(result).__name__,'duration_ms':(datetime.now(timezone.utc)-started).total_seconds()*1000})
            return result
        if isinstance(value,dict): return {k:await self._resolve_value(v,ctx) for k,v in value.items()}
        if isinstance(value,list): return [await self._resolve_value(v,ctx) for v in value]
        return value

    async def evaluate_condition(self,c,ctx=None):
        typ=c.get('type')
        if typ=='and': return all([await self.evaluate_condition(x,ctx) for x in c['conditions']])
        if typ=='or': return any([await self.evaluate_condition(x,ctx) for x in c['conditions']])
        if typ=='not': return not await self.evaluate_condition(c['condition'],ctx)
        if typ=='template':
            try: value=await self.expressions.evaluate(c['expression'],context=self._expression_context(ctx),syntax='jinja' if '{{' in c['expression'] else 'native')
            except ExpressionError as exc: raise RuntimeError(f'Expression {exc.category}') from None
            return self.expressions._bool(value)
        async with db.acquire() as conn:
            if typ=='state':
                row=await conn.fetchrow('SELECT state,attributes FROM entities WHERE id=$1 AND enabled',int(c['entity_ref']))
                if not row: raise LookupError('Entity not found')
                value=(row['attributes'] or {}).get(c['attribute']) if c.get('attribute') else row['state']
                return value==c['state']
            if typ=='numeric_state':
                row=await conn.fetchrow('SELECT state,attributes FROM entities WHERE id=$1 AND enabled',int(c['entity_ref']))
                if not row: raise LookupError('Entity not found')
                value=(row['attributes'] or {}).get(c['attribute']) if c.get('attribute') else row['state']
                if isinstance(value,bool): return False
                try: n=float(value)
                except (TypeError,ValueError): return False
                return (c.get('above') is None or n>float(c['above'])) and (c.get('below') is None or n<float(c['below']))
        if typ=='time':
            now=datetime.now(self.timezone); current=now.time(); weekdays=c.get('weekdays')
            if weekdays and now.strftime('%a').lower()[:3] not in [str(x).lower()[:3] for x in weekdays]: return False
            after=dt_time.fromisoformat(c['after']) if c.get('after') else None; before=dt_time.fromisoformat(c['before']) if c.get('before') else None
            if after and before and after>before: return current>=after or current<before
            return (after is None or current>=after) and (before is None or current<before)
        raise AutomationValidationError('Unsupported condition')

    async def inspect_automation(self, automation_id):
        automation=await self.store.get(automation_id)
        async with db.acquire() as conn:
            rows=await conn.fetch("""SELECT trigger_id,intended_fire_at,status,catch_up,actual_fire_at FROM automation_schedule_ledger WHERE automation_id=$1 ORDER BY intended_fire_at DESC LIMIT 100""",_as_uuid(automation_id))
        schedule=[dict(r) for r in rows]
        future=[r for r in schedule if r['status']=='scheduled']
        caught=[r for r in schedule if r['catch_up']]
        automation['schedule']={'next_occurrence':min((r['intended_fire_at'] for r in future),default=None),'last_occurrence':max((r['actual_fire_at'] for r in schedule if r['actual_fire_at']),default=None),'last_caught_up':max((r['actual_fire_at'] for r in caught if r['actual_fire_at']),default=None)}
        return automation

    async def list_runs(self,automation_id,limit=100):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT * FROM automation_runs WHERE automation_id=$1 ORDER BY started_at DESC LIMIT $2',_as_uuid(automation_id),min(max(int(limit),1),1000))
        return [dict(r) for r in rows]
    async def get_run(self,run_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM automation_runs WHERE run_id=$1',_as_uuid(run_id))
        if not row: raise LookupError('Run not found')
        return dict(row)
