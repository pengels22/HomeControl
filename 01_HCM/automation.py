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
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .expressions import ExpressionEngine, ExpressionError, Snapshot, Undefined

MODES = {'single','restart','queued','parallel'}
STATUSES = {'running','success','failed','cancelled','skipped','HCM_RESTART'}
ERRORS = {'validation error','missing entity','unavailable target','service unavailable','service failure','timeout','cancelled','internal error'}
MAX_TRACE_STEPS = 200
MAX_TRACE_BYTES = 64_000
MAX_ACTION_DEPTH = 10
MAX_REPEAT_ITERATIONS = 100
MAX_FOREACH_ITEMS = 100
MAX_PARALLEL_BRANCHES = 10
MIN_WAIT_INTERVAL = 0.1

class AutomationValidationError(ValueError): pass
class AutomationStopped(Exception): pass
class AutomationControlArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    # UUID is the durable identity.  ``target`` is resolved by the service
    # registry when callers use an Automation entity target.
    automation_id: str | None = None
    evaluate_conditions: bool = True
    caller_id: str | None = None
    invocation_chain: list[str] = Field(default_factory=list)
    invocation_depth: int = 0


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

def _validate_timeout(value):
    if value is None: return
    try: seconds=float(value)
    except (TypeError,ValueError): raise AutomationValidationError('Invalid timeout')
    if seconds<0 or seconds>86400: raise AutomationValidationError('Timeout must be 0..86400 seconds')

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
        if not isinstance(t,dict) or set(t)-{'type','entity_ref','from','to','attribute','for','event_type','provider_id','instance_id','device_ref','payload','times','time','every_minutes','every_hours','minute','hour','sun','offset','above','below'}: raise AutomationValidationError('Invalid trigger definition')
        typ=t.get('type')
        if typ=='state':
            if 'entity_ref' not in t: raise AutomationValidationError('State trigger needs entity_ref')
            t=dict(t); t['entity_ref']=await self._entity_ref(t['entity_ref'])
            if 'for' in t and (not isinstance(t['for'],(int,float)) or t['for']<0): raise AutomationValidationError('for must be non-negative seconds')
        elif typ=='event':
            if not isinstance(t.get('event_type'),str) or not t['event_type']: raise AutomationValidationError('Event trigger needs event_type')
        elif typ=='numeric_state':
            if 'entity_ref' not in t: raise AutomationValidationError('Numeric state trigger needs entity_ref')
            if t.get('above') is None and t.get('below') is None: raise AutomationValidationError('Numeric state trigger needs above or below')
            if t.get('for') is not None and (not isinstance(t['for'],(int,float)) or t['for']<0): raise AutomationValidationError('for must be non-negative seconds')
            for key in ('above','below'):
                if t.get(key) is not None:
                    try: float(t[key])
                    except (TypeError,ValueError): raise AutomationValidationError(f'{key} must be numeric')
            t=dict(t); t['entity_ref']=await self._entity_ref(t['entity_ref']); t['trigger_id']=trigger_id(t)
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
        if isinstance(c,list):
            for child in c: await self._validate_condition(child)
            return
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

    async def _validate_action(self,a,depth=0):
        if not isinstance(a,dict): raise AutomationValidationError('Action must be an object')
        if depth>MAX_ACTION_DEPTH: raise AutomationValidationError('Action nesting exceeds limit')
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
        elif typ=='if':
            if not isinstance(a.get('conditions'),(dict,list)) or not isinstance(a.get('then'),list) or (a.get('else') is not None and not isinstance(a.get('else'),list)): raise AutomationValidationError('if needs conditions and then sequence')
            await self._validate_condition(a['conditions'])
            for child in a['then'] + (a.get('else') or []): await self._validate_action(child,depth+1)
        elif typ=='choose':
            choices=a.get('choices',a.get('choose'))
            if not isinstance(choices,list): raise AutomationValidationError('choose needs choices')
            for choice in choices:
                if not isinstance(choice,dict) or not isinstance(choice.get('conditions'),(dict,list)) or not isinstance(choice.get('sequence'),list): raise AutomationValidationError('Malformed choose entry')
                await self._validate_condition(choice['conditions'])
                for child in choice['sequence']: await self._validate_action(child,depth+1)
            if a.get('default') is not None:
                if not isinstance(a['default'],list): raise AutomationValidationError('choose default must be a sequence')
                for child in a['default']: await self._validate_action(child,depth+1)
        elif typ=='wait':
            if not (a.get('condition') is not None or isinstance(a.get('expression'),str)): raise AutomationValidationError('wait needs condition or expression')
            if a.get('condition') is not None: await self._validate_condition(a['condition'])
            _validate_timeout(a.get('timeout'))
        elif typ=='wait_for_trigger':
            if not isinstance(a.get('triggers'),list) or not a['triggers']: raise AutomationValidationError('wait_for_trigger needs triggers')
            for trigger in a['triggers']: await self._validate_trigger(trigger)
            _validate_timeout(a.get('timeout'))
        elif typ=='repeat':
            sequence=a.get('sequence')
            if not isinstance(sequence,list) or not sequence: raise AutomationValidationError('repeat needs a sequence')
            modes=sum(a.get(k) is not None for k in ('count','while','until','for_each'))
            if modes!=1: raise AutomationValidationError('repeat needs exactly one mode')
            if a.get('count') is not None:
                if isinstance(a['count'],str) and ('{{' in a['count'] or a['count'].strip()):
                    await self._validate_expression_values(a['count'])
                else:
                    try:
                        if int(a['count'])<0 or int(a['count'])>MAX_REPEAT_ITERATIONS: raise ValueError
                    except (TypeError,ValueError): raise AutomationValidationError('repeat count exceeds limit or is invalid')
            if a.get('while') is not None: await self._validate_condition(a['while'])
            if a.get('until') is not None: await self._validate_condition(a['until'])
            for child in sequence: await self._validate_action(child,depth+1)
        elif typ=='parallel':
            branches=a.get('branches',a.get('parallel'))
            if not isinstance(branches,list) or not branches or len(branches)>MAX_PARALLEL_BRANCHES: raise AutomationValidationError('parallel branch limit exceeded')
            for branch in branches:
                if not isinstance(branch,list): raise AutomationValidationError('parallel branch must be a sequence')
                for child in branch: await self._validate_action(child,depth+1)
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
    kind: str='automation'
    invocation_chain: tuple[str,...]=()
    caller_id: str|None=None
    evaluate_conditions: bool=True

class AutomationEngine:
    def __init__(self, registry, *, timezone_name='UTC', latitude=None, longitude=None, store=None):
        self.registry=registry; self.store=store or AutomationStore(); self.timezone=ZoneInfo(timezone_name)
        self.sun=SunCalculator(latitude,longitude,timezone_name) if latitude is not None and longitude is not None else None
        self.expressions=ExpressionEngine(timezone_name=timezone_name)
        self.active=defaultdict(dict); self.queues=defaultdict(deque); self.timers={}; self.tasks=set(); self.task=None; self.wake=asyncio.Event(); self.scheduler_started_at=None; self.waiters=[]; self._services_registered=False
        self.max_invocation_depth=10
        self._automation_device_id=None

    async def start(self):
        await self._register_control_services()
        async with db.acquire() as conn:
            await conn.execute("UPDATE automation_runs SET status='HCM_RESTART',ended_at=now(),result='HCM restart',error_category='cancelled' WHERE status='running'")
            self.cursor=int(await conn.fetchval("SELECT last_event_id FROM automation_engine_state WHERE state_key='integration_events'") or 0)
            previous=await conn.fetchval("SELECT last_seen_at FROM automation_scheduler_state WHERE state_key='scheduler'")
        self.scheduler_started_at=datetime.now(timezone.utc); await self.reconstruct_schedules(previous,self.scheduler_started_at)
        async with db.acquire() as conn: await conn.execute("UPDATE automation_scheduler_state SET last_seen_at=$1,updated_at=now() WHERE state_key='scheduler'",self.scheduler_started_at)
        await self._sync_automation_entities()
        if not self.task or self.task.done(): self.task=asyncio.create_task(self._loop())

    async def _sync_automation_entities(self):
        """Project durable automations into the normal entity target model."""
        try:
            context=self.registry.context('hcm_native')
            self._automation_device_id=await context.device('automation-registry','Automations',available=True)
            for automation in await self.store.list(): await self._sync_automation_entity(context,automation)
        except Exception:
            # Entity projection is additive; an unavailable database/provider must
            # not prevent the scheduler from starting.
            self._automation_device_id=None

    async def _sync_automation_entity(self,context,automation):
        if self._automation_device_id is None: return
        aid=str(automation['automation_id']); entity_id=f'automation.{aid.replace("-","")}'
        ref=await context.entity(aid,entity_id,self._automation_device_id,automation.get('name',aid))
        await context.availability(ref,True)
        await context.state(ref,'on' if automation.get('enabled') else 'off',attributes={'automation_id':aid,'mode':automation.get('mode','single'),'revision':automation.get('revision',0)},available=True)

    async def create_automation(self,definition):
        automation=await self.store.create(definition)
        try: await self._sync_automation_entity(self.registry.context('hcm_native'),automation)
        except Exception: pass
        return automation

    async def stop(self):
        for runs in self.active.values():
            for ctx in runs.values(): ctx.cancelled.set()
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True); self.task=None
        for task in list(self.timers.values()): task.cancel()
        for task in list(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks,return_exceptions=True)
        self.timers.clear(); self.tasks.clear()
        for waiter in list(self.waiters): waiter['future'].cancel()
        self.waiters.clear()

    async def _register_control_services(self):
        if self._services_registered: return
        try:
            context=self.registry.context('hcm_native')
            await context.service('automation','turn_on',AutomationControlArgs,self._service_turn_on)
            await context.service('automation','turn_off',AutomationControlArgs,self._service_turn_off)
            await context.service('automation','trigger',AutomationControlArgs,self._service_trigger)
            self._services_registered=True
        except Exception:
            self._services_registered=False

    async def _automation_id_from_target(self,target,automation_id=None):
        if automation_id: return automation_id
        if target is None: raise ValueError('Automation target required')
        async with db.acquire() as conn:
            value=await conn.fetchval("SELECT attributes->>'automation_id' FROM entities WHERE id=$1 AND domain='automation'",int(target))
        if not value: raise LookupError('Automation target unavailable')
        return value

    async def _service_turn_on(self,args,target): return await self.set_enabled(await self._automation_id_from_target(target,args.automation_id),True)
    async def _service_turn_off(self,args,target): return await self.set_enabled(await self._automation_id_from_target(target,args.automation_id),False)
    async def _service_trigger(self,args,target):
        automation=await self.store.get(await self._automation_id_from_target(target,args.automation_id))
        if not automation.get('enabled'):
            return {'run_id':None,'status':'disabled_target'}
        run_id=await self.trigger(automation,source='automation_service',caller_id=args.caller_id,
                                  invocation_chain=args.invocation_chain,evaluate_conditions=args.evaluate_conditions)
        return {'run_id':str(run_id) if run_id else None,'status':'blocked' if run_id is None else 'started'}

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
        automation=await self.store.update(automation_id,definition)
        try: await self._sync_automation_entity(self.registry.context('hcm_native'),automation)
        except Exception: pass
        return automation

    async def set_enabled(self, automation_id, enabled):
        if not enabled: await self.cancel_automation(automation_id)
        automation=await self.store.set_enabled(automation_id,enabled)
        try: await self._sync_automation_entity(self.registry.context('hcm_native'),automation)
        except Exception: pass
        return automation

    async def delete_automation(self, automation_id):
        await self.cancel_automation(automation_id)
        deleted=await self.store.delete(automation_id)
        if deleted:
            try:
                async with db.acquire() as conn: await conn.execute("DELETE FROM entities WHERE provider_id='hcm_native' AND domain='automation' AND external_entity_id=$1",str(automation_id))
            except Exception: pass
        return deleted


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
            self._notify_waiters(event)
            for automation in automations:
                if automation['enabled'] and any(self._trigger_matches(t,event,automation_id=str(automation['automation_id'])) for t in self._json_field(automation['trigger_definitions'])):
                    await self.trigger(automation,source='event',event=event)
            async with db.acquire() as conn: await conn.execute("UPDATE automation_engine_state SET last_event_id=$1,updated_at=now() WHERE state_key='integration_events'",event_id)
            self.cursor=event_id
        return len(events)

    def _json_field(self,v): return json.loads(v) if isinstance(v,str) else (v or [])
    def _numeric_value(self,t,payload):
        value=(payload.get('attributes') or {}).get(t.get('attribute')) if t.get('attribute') else payload.get('state')
        if isinstance(value,bool): return None
        try: return float(value)
        except (TypeError,ValueError): return None
    def _numeric_matches(self,t,e,automation_id=None):
        current=self._numeric_value(t,e.get('payload') or {})
        previous_payload={'state':(e.get('payload') or {}).get('previous_state'),'attributes':(e.get('payload') or {}).get('previous_attributes',{})}
        previous=self._numeric_value(t,previous_payload)
        if current is None: return False
        matches=(t.get('above') is None or current>float(t['above'])) and (t.get('below') is None or current<float(t['below']))
        was=(previous is not None and (t.get('above') is None or previous>float(t['above'])) and (t.get('below') is None or previous<float(t['below'])))
        if not matches or was: return False
        if t.get('for'):
            key=('numeric',str(automation_id or ''),t.get('trigger_id') or trigger_id(t),str(t.get('entity_ref')))
            self._start_timer(key,t,e,current); return False
        return True
    def _trigger_matches_wait(self,t,e):
        if t.get('type')=='numeric_state': return self._numeric_matches(t,e)
        return self._trigger_matches(t,e)
    def _notify_waiters(self,event):
        for waiter in list(self.waiters):
            if waiter['future'].done(): continue
            for trigger in waiter['triggers']:
                if self._trigger_matches_wait(trigger,event):
                    waiter['future'].set_result({'trigger':trigger,'event':_safe(event)})
                    break
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
        if typ=='numeric_state':
            return self._numeric_matches(t,e,automation_id)
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
                    if t.get('type')=='numeric_state':
                        try: numeric=float(current); still_matches=(t.get('above') is None or numeric>float(t['above'])) and (t.get('below') is None or numeric<float(t['below']))
                        except (TypeError,ValueError): still_matches=False
                    else: still_matches=t.get('to') is None or current==t.get('to')
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

    async def trigger(self,automation,*,source='manual',event=None,dry_run=False,schedule=None,kind='automation',variables=None,invocation_chain=None,caller_id=None,evaluate_conditions=True):
        aid=str(automation['automation_id']); mode=automation['mode']; active=self.active[aid]
        identity=f'{kind}:{aid}'
        chain=tuple(str(x) for x in (invocation_chain or ()))
        if identity in chain or len(chain)>=self.max_invocation_depth:
            return None
        if mode=='single' and active: return None
        if mode=='restart' and active:
            for ctx in active.values(): ctx.cancelled.set()
        if mode=='queued' and len(active)+len(self.queues[aid])>=int(automation['max_runs']): return None
        if mode=='parallel' and len(active)>=int(automation['max_runs']): return None
        ctx=RunContext(automation,uuid4(),[],asyncio.Event(),dry_run,variables=dict(variables or {}),trigger={},kind=kind,invocation_chain=chain+(identity,),caller_id=caller_id,evaluate_conditions=evaluate_conditions)
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
            if ctx.evaluate_conditions and a.get('condition_definition') and not await self.evaluate_condition(self._json_field(a['condition_definition']),ctx): status='skipped'; result='condition false'
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
        owner=_as_uuid(ctx.automation['automation_id'])
        async with db.acquire() as conn:
            await conn.execute('INSERT INTO automation_runs(run_id,automation_id,script_id,run_kind,trigger_source,trigger_event_id,started_at,status,mode,trace) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)',ctx.run_id,owner if ctx.kind=='automation' else None,owner if ctx.kind=='script' else None,ctx.kind,source,(event or {}).get('event_id'),started,status,ctx.automation['mode'],json.dumps(ctx.trace))
    async def _finish_run(self,ctx,status,result,category,started):
        trace=_safe(ctx.trace)[-MAX_TRACE_STEPS:]
        while trace and len(json.dumps(trace))>MAX_TRACE_BYTES: trace.pop(0)
        raw=json.dumps(trace)
        async with db.acquire() as conn:
            await conn.execute('UPDATE automation_runs SET ended_at=now(),status=$2,result=$3,error_category=$4,trace=$5::jsonb WHERE run_id=$1',ctx.run_id,status,result,category,raw)
            if ctx.kind=='automation':
                await conn.execute('UPDATE automations SET last_triggered_at=CASE WHEN $2 IN (\'success\',\'failed\',\'skipped\') THEN now() ELSE last_triggered_at END,last_run_status=$2 WHERE automation_id=$1',_as_uuid(ctx.automation['automation_id']),status)

    async def _action(self,ctx,a,depth=0):
        if ctx.cancelled.is_set(): raise asyncio.CancelledError
        if depth>MAX_ACTION_DEPTH: raise AutomationValidationError('Action nesting exceeds limit')
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
        elif typ=='if':
            result=await self.evaluate_condition(a['conditions'],ctx); branch='then' if result else 'else'; skipped='else' if result else 'then'
            ctx.trace.append({'step':'if','condition_result':result,'selected_branch':branch,'skipped_branch':skipped})
            for child in a.get(branch,[]): await self._action(ctx,child,depth+1)
        elif typ=='choose':
            choices=a.get('choices',a.get('choose',[])); selected=None
            for index,choice in enumerate(choices):
                result=await self.evaluate_condition(choice['conditions'],ctx); ctx.trace.append({'step':'choose_evaluate','choice':index,'result':result})
                if result:
                    selected=index
                    for child in choice.get('sequence',[]): await self._action(ctx,child,depth+1)
                    break
            if selected is None:
                ctx.trace.append({'step':'choose_default','selected':bool(a.get('default'))})
                for child in a.get('default',[]): await self._action(ctx,child,depth+1)
            else: ctx.trace.append({'step':'choose_selected','choice':selected})
        elif typ=='wait':
            await self._wait_condition(ctx,a)
        elif typ=='wait_for_trigger':
            await self._wait_for_trigger(ctx,a)
        elif typ=='repeat':
            await self._repeat(ctx,a,depth)
        elif typ=='parallel':
            await self._parallel(ctx,a,depth)
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
            if a['domain']=='automation' and a['service']=='trigger':
                arguments.update({'caller_id':f'{ctx.kind}:{ctx.automation.get("automation_id")}', 'invocation_chain':list(ctx.invocation_chain), 'invocation_depth':len(ctx.invocation_chain)})
            elif a['domain']=='script' and a['service']=='run':
                inputs=dict(arguments.get('inputs') or {})
                inputs.update({'_hcm_caller_id':f'{ctx.kind}:{ctx.automation.get("automation_id")}', '_hcm_invocation_chain':list(ctx.invocation_chain)})
                arguments['inputs']=inputs
            ctx.trace.append({'step':'service','domain':a['domain'],'service':a['service'],'target':a.get('target_entity_ref'),'arguments':_safe(arguments),'physical_mutation':bool(declaration.get('mutates_physical_state',False))})
            result=None
            if not ctx.dry_run:
                if not provider_id: raise LookupError('Service provider unavailable')
                result=await self.registry.services.invoke(provider_id,a['domain'],a['service'],arguments,target_entity_id=a.get('target_entity_ref'),instance_id=a.get('instance_id'))
            if a.get('response_variable'): ctx.variables[a['response_variable']]=result if result is not None else Undefined
        ctx.trace.append({'step':'action_end','type':typ,'at':datetime.now(timezone.utc).isoformat()})

    async def _wait_condition(self,ctx,a):
        started=datetime.now(timezone.utc); timeout=float(a.get('timeout',86400)); deadline=asyncio.get_running_loop().time()+timeout if timeout is not None else None
        while True:
            if ctx.cancelled.is_set(): raise asyncio.CancelledError
            result=await self.evaluate_condition(a['condition'],ctx) if a.get('condition') is not None else self.expressions._bool(await self.expressions.evaluate(a['expression'],context=self._expression_context(ctx),syntax='jinja' if '{{' in a['expression'] else 'native'))
            if result:
                ctx.variables['wait']={'completed':True,'timed_out':False}; ctx.trace.append({'step':'wait','result':'matched','duration_ms':(datetime.now(timezone.utc)-started).total_seconds()*1000}); return
            if deadline is not None and asyncio.get_running_loop().time()>=deadline: break
            try: await asyncio.wait_for(ctx.cancelled.wait(),timeout=MIN_WAIT_INTERVAL)
            except asyncio.TimeoutError: pass
        ctx.variables['wait']={'completed':False,'timed_out':True}; ctx.trace.append({'step':'wait','result':'timeout'})
        if not a.get('continue_on_timeout',True): raise AutomationStopped('wait timeout')

    async def _wait_for_trigger(self,ctx,a):
        future=asyncio.get_running_loop().create_future(); waiter={'future':future,'triggers':a['triggers']}; self.waiters.append(waiter); started=datetime.now(timezone.utc); cancel_task=asyncio.create_task(ctx.cancelled.wait())
        timeout=a.get('timeout');
        try:
            done,_=await asyncio.wait({future,cancel_task},timeout=float(timeout) if timeout is not None else None,return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done: raise asyncio.CancelledError
            if not done: raise asyncio.TimeoutError
            matched=future.result()
            ctx.variables['wait']={'trigger':matched['trigger'],'event':matched['event'],'timed_out':False}; ctx.trace.append({'step':'wait_for_trigger','result':'matched','duration_ms':(datetime.now(timezone.utc)-started).total_seconds()*1000})
        except asyncio.TimeoutError:
            ctx.variables['wait']={'trigger':None,'event':None,'timed_out':True}; ctx.trace.append({'step':'wait_for_trigger','result':'timeout'})
            if not a.get('continue_on_timeout',True): raise AutomationStopped('wait_for_trigger timeout')
        finally:
            cancel_task.cancel()
            if waiter in self.waiters: self.waiters.remove(waiter)

    async def _repeat(self,ctx,a,depth):
        sequence=a['sequence']; limit=MAX_REPEAT_ITERATIONS; count=a.get('count'); mode='count'
        if count is not None:
            value=await self._resolve_value(count,ctx); iterations=int(value)
            if iterations<0 or iterations>limit: raise AutomationValidationError('repeat count exceeds limit')
            values=[None]*iterations
        elif a.get('for_each') is not None:
            mode='for_each'; values=await self._resolve_value(a['for_each'],ctx)
            if not isinstance(values,list) or len(values)>MAX_FOREACH_ITEMS: raise AutomationValidationError('for_each exceeds limit')
        else:
            mode='while' if a.get('while') is not None else 'until'; values=[None]*limit
        for index,item in enumerate(values):
            if mode=='while' and not await self.evaluate_condition(a['while'],ctx): break
            ctx.variables['repeat']={'index':index,'first':index==0,'last':index==len(values)-1,'item':item}
            ctx.trace.append({'step':'repeat','iteration':index,'context':_safe(ctx.variables['repeat'])})
            for child in sequence: await self._action(ctx,child,depth+1)
            if mode=='until' and await self.evaluate_condition(a['until'],ctx): break
        ctx.variables.pop('repeat',None)

    async def _parallel(self,ctx,a,depth):
        branches=a.get('branches',a.get('parallel',[]))
        async def run_branch(index,sequence):
            child=RunContext(ctx.automation,ctx.run_id,ctx.trace,ctx.cancelled,ctx.dry_run,variables=dict(ctx.variables),trigger=ctx.trigger,kind=ctx.kind,invocation_chain=ctx.invocation_chain,caller_id=ctx.caller_id,evaluate_conditions=ctx.evaluate_conditions)
            child.trace=[]
            try:
                for action in sequence: await self._action(child,action,depth+1)
                return {'branch':index,'status':'success','trace':child.trace}
            except asyncio.CancelledError: return {'branch':index,'status':'cancelled','trace':child.trace}
            except Exception as exc: return {'branch':index,'status':'failed','error':type(exc).__name__,'trace':child.trace}
        results=await asyncio.gather(*(run_branch(i,b) for i,b in enumerate(branches)))
        ctx.trace.append({'step':'parallel','branches':_safe(results),'result':'success' if all(x['status']=='success' for x in results) else 'partial_failure'})
        if any(x['status']=='failed' for x in results): raise RuntimeError('parallel branch failed')

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
        if isinstance(c,list):
            return all([await self.evaluate_condition(x,ctx) for x in c])
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
    async def list_script_runs(self,script_id,limit=100):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT * FROM automation_runs WHERE script_id=$1 ORDER BY started_at DESC LIMIT $2',_as_uuid(script_id),min(max(int(limit),1),1000))
        return [dict(r) for r in rows]

    async def get_run(self,run_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM automation_runs WHERE run_id=$1',_as_uuid(run_id))
        if not row: raise LookupError('Run not found')
        return dict(row)
