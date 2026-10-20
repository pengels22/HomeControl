"""Native HCM helpers, scripts, and scenes.

All state is represented by the normal integration entity registry and all
mutations use the normal Service Registry. This module contains no GPIO or
provider-specific paths.
"""
from __future__ import annotations
import asyncio, json, re
from datetime import datetime, timezone, timedelta
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from . import db
from .integrations.provider import ProviderInfo, Diagnostics
from .integrations.registry import Registry

class Empty(BaseModel): model_config=ConfigDict(extra='forbid')
class NumberArg(BaseModel): model_config=ConfigDict(extra='forbid'); value: float
class TextArg(BaseModel): model_config=ConfigDict(extra='forbid'); value: str
class OptionArg(BaseModel): model_config=ConfigDict(extra='forbid'); option: str
class DateTimeArg(BaseModel):
    model_config=ConfigDict(extra='forbid'); value: str|None=None; date: str|None=None; time: str|None=None
class CounterArg(BaseModel): model_config=ConfigDict(extra='forbid'); value: int|None=None
class TimerArg(BaseModel): model_config=ConfigDict(extra='forbid'); duration: float|None=None
class ScriptArg(BaseModel): model_config=ConfigDict(extra='forbid'); inputs: dict = Field(default_factory=dict)

INFO=ProviderInfo('hcm_native','HCM Native Primitives',capabilities={'helpers':True,'scripts':True,'scenes':True,'states':True,'events':True,'services':True},internal=True)
HELPER_TYPES={'input_boolean','input_button','input_number','input_text','input_select','input_datetime','counter','timer','schedule'}

class NativePrimitives:
    def __init__(self, registry: Registry, *, timezone_name='UTC', automation_engine=None):
        self.registry=registry; self.context=None; self.engine=automation_engine; self.timezone_name=timezone_name
        self.tasks={}; self.started=False
    async def start(self):
        await self.registry.register(INFO,enabled=True,configured=True); await self.registry.status('hcm_native','connected')
        self.context=self.registry.context('hcm_native'); self.started=True
        await self._register_services(); await self._restore_helpers(); await self._restore_timers(); await self._restore_schedules()
    async def stop(self):
        for task in list(self.tasks.values()): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.tasks.clear(); self.started=False
    async def _register_services(self):
        c=self.context
        await c.service('input_boolean','turn_on',Empty,self._input_boolean_on,target_required=True,target_domains=('input_boolean',))
        await c.service('input_boolean','turn_off',Empty,self._input_boolean_off,target_required=True,target_domains=('input_boolean',))
        await c.service('input_boolean','toggle',Empty,self._input_boolean_toggle,target_required=True,target_domains=('input_boolean',))
        await c.service('input_button','press',Empty,self._button_press,target_required=True,target_domains=('input_button',))
        await c.service('input_number','set_value',NumberArg,self._number_set,target_required=True,target_domains=('input_number',))
        await c.service('input_number','increment',Empty,self._number_increment,target_required=True,target_domains=('input_number',))
        await c.service('input_number','decrement',Empty,self._number_decrement,target_required=True,target_domains=('input_number',))
        await c.service('input_text','set_value',TextArg,self._text_set,target_required=True,target_domains=('input_text',))
        await c.service('input_select','select_option',OptionArg,self._select_option,target_required=True,target_domains=('input_select',))
        await c.service('input_select','select_next',Empty,self._select_next,target_required=True,target_domains=('input_select',))
        await c.service('input_select','select_previous',Empty,self._select_previous,target_required=True,target_domains=('input_select',))
        await c.service('input_datetime','set_datetime',DateTimeArg,self._datetime_set,target_required=True,target_domains=('input_datetime',))
        for name,callback in (('increment',self._counter_increment),('decrement',self._counter_decrement),('reset',self._counter_reset),('set_value',self._counter_set)):
            await c.service('counter',name,CounterArg if name=='set_value' else Empty,callback,target_required=True,target_domains=('counter',))
        for name,callback in (('start',self._timer_start),('pause',self._timer_pause),('cancel',self._timer_cancel),('finish',self._timer_finish)):
            await c.service('timer',name,TimerArg if name=='start' else Empty,callback,target_required=True,target_domains=('timer',))
        await c.service('script','run',ScriptArg,self._script_run,target_required=True,target_domains=('script',))
        await c.service('scene','turn_on',Empty,self._scene_turn_on,target_required=True,target_domains=('scene',))
    async def _helper(self,entity_ref,kind=None):
        async with db.acquire() as conn:
            row=await conn.fetchrow('SELECT h.*,e.state,e.attributes FROM native_helpers h JOIN entities e ON e.id=h.entity_ref WHERE h.entity_ref=$1 AND ($2::text IS NULL OR h.helper_type=$2)',int(entity_ref),kind)
        if not row: raise LookupError('Native helper not found')
        return row
    async def _set(self,row,value,attrs=None):
        await self.context.state(int(row['entity_ref']),value,attributes=attrs or {})
        return {'entity_ref':int(row['entity_ref']),'state':value}
    async def _input_boolean_on(self,a,t): return await self._set(await self._helper(t,'input_boolean'),'on')
    async def _input_boolean_off(self,a,t): return await self._set(await self._helper(t,'input_boolean'),'off')
    async def _input_boolean_toggle(self,a,t):
        row=await self._helper(t,'input_boolean'); return await self._set(row,'off' if row['state']=='on' else 'on')
    async def _button_press(self,a,t):
        row=await self._helper(t,'input_button'); attrs=dict(row['config']); attrs.update({'pressed_at':datetime.now(timezone.utc).isoformat(),'sequence':int(attrs.get('sequence',0))+1});
        async with db.acquire() as conn: await conn.execute('UPDATE native_helpers SET config=$2::jsonb,updated_at=now() WHERE helper_id=$1',row['helper_id'],json.dumps(attrs))
        return await self._set(row,None,attrs)
    async def _number_set(self,a,t):
        row=await self._helper(t,'input_number'); value=float(a.value); cfg=row['config'] or {}; minimum=float(cfg['min']); maximum=float(cfg['max'])
        if value<minimum or value>maximum: raise ValueError('Value outside input_number bounds')
        return await self._set(row,value,{'unit':cfg.get('unit'),'min':minimum,'max':maximum,'step':cfg.get('step')})
    async def _number_increment(self,a,t): return await self._number_set(NumberArg(value=float((await self._helper(t,'input_number'))['state'] or 0)+float((await self._helper(t,'input_number'))['config'].get('step',1))),t)
    async def _number_decrement(self,a,t): return await self._number_set(NumberArg(value=float((await self._helper(t,'input_number'))['state'] or 0)-float((await self._helper(t,'input_number'))['config'].get('step',1))),t)
    async def _text_set(self,a,t):
        row=await self._helper(t,'input_text'); value=str(a.value); maximum=int((row['config'] or {}).get('max_length',255))
        if len(value)>maximum: raise ValueError('input_text exceeds max_length')
        return await self._set(row,value)
    async def _select_option(self,a,t):
        row=await self._helper(t,'input_select'); options=(row['config'] or {}).get('options',[])
        if a.option not in options: raise ValueError('Unknown input_select option')
        return await self._set(row,a.option)
    async def _select_next(self,a,t): return await self._select_relative(t,1)
    async def _select_previous(self,a,t): return await self._select_relative(t,-1)
    async def _select_relative(self,t,delta):
        row=await self._helper(t,'input_select'); options=(row['config'] or {}).get('options',[]); index=options.index(row['state']) if row['state'] in options else 0
        return await self._set(row,options[(index+delta)%len(options)])
    async def _datetime_set(self,a,t):
        row=await self._helper(t,'input_datetime'); cfg=row['config'] or {}; value=a.value or ((a.date or '')+'T'+(a.time or ''))
        if not value: raise ValueError('datetime value required')
        try: parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError: raise ValueError('Invalid datetime value') from None
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=__import__('zoneinfo').zoneinfo.ZoneInfo(self.timezone_name))
        return await self._set(row,parsed.isoformat(),{'date':parsed.date().isoformat(),'time':parsed.time().isoformat()})
    async def _counter(self,a,t,op):
        row=await self._helper(t,'counter'); cfg=row['config'] or {}; current=int(row['state'] or 0); step=int(cfg.get('step',1)); value={'increment':current+step,'decrement':current-step,'reset':int(cfg.get('initial',0)),'set':int(a.value)}[op]
        if cfg.get('min') is not None and value<int(cfg['min']): raise ValueError('Counter below minimum')
        if cfg.get('max') is not None and value>int(cfg['max']): raise ValueError('Counter above maximum')
        return await self._set(row,value)
    async def _counter_increment(self,a,t): return await self._counter(a,t,'increment')
    async def _counter_decrement(self,a,t): return await self._counter(a,t,'decrement')
    async def _counter_reset(self,a,t): return await self._counter(a,t,'reset')
    async def _counter_set(self,a,t): return await self._counter(a,t,'set')
    async def _timer_start(self,a,t):
        row=await self._helper(t,'timer'); cfg=row['config'] or {}; seconds=float(a.duration if a.duration is not None else cfg.get('duration',0));
        if seconds<=0 or seconds>86400: raise ValueError('Timer duration must be 0..86400 seconds')
        expected=datetime.now(timezone.utc)+timedelta(seconds=seconds); attrs={'duration':seconds,'remaining':seconds,'started_at':datetime.now(timezone.utc).isoformat(),'expected_finish':expected.isoformat()}
        await self._set(row,'active',attrs); await self.context.emit('hcm_native.timer.started',attrs,entity_id=row['entity_ref']); await self._timer_task(row['entity_ref'],seconds); return attrs
    async def _timer_task(self,entity_ref,seconds):
        old=self.tasks.pop(('timer',int(entity_ref)),None)
        if old: old.cancel()
        async def finish():
            try: await asyncio.sleep(seconds); await self._finish_timer(entity_ref)
            except asyncio.CancelledError: pass
        task=asyncio.create_task(finish()); self.tasks[('timer',int(entity_ref))]=task; task.add_done_callback(lambda _:self.tasks.pop(('timer',int(entity_ref)),None))
    async def _finish_timer(self,t):
        row=await self._helper(t,'timer')
        if row['state']!='active': return {'status':'ignored'}
        await self._set(row,'idle',{'remaining':0}); await self.context.emit('hcm_native.timer.finished',{'entity_ref':int(t)},entity_id=t); return {'status':'finished'}
    async def _timer_pause(self,a,t):
        row=await self._helper(t,'timer');
        if row['state']!='active': return {'status':'ignored'}
        expected=datetime.fromisoformat((row['attributes'] or {}).get('expected_finish')) if (row['attributes'] or {}).get('expected_finish') else datetime.now(timezone.utc); remaining=max(0,(expected-datetime.now(timezone.utc)).total_seconds()); task=self.tasks.pop(('timer',int(t)),None)
        if task: task.cancel()
        return await self._set(row,'paused',{'remaining':remaining})
    async def _timer_cancel(self,a,t):
        task=self.tasks.pop(('timer',int(t)),None)
        if task: task.cancel()
        row=await self._helper(t,'timer'); result=await self._set(row,'idle',{'remaining':0}); await self.context.emit('hcm_native.timer.cancelled',{'entity_ref':int(t)},entity_id=t); return result
    async def _timer_finish(self,a,t): return await self._finish_timer(t)
    async def _restore_helpers(self):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT h.*,e.state,e.attributes FROM native_helpers h JOIN entities e ON e.id=h.entity_ref WHERE h.enabled')
        for row in rows:
            try:
                if row['helper_type'] not in ('timer','schedule'): await self.context.availability(row['entity_ref'],True)
            except Exception:
                continue

    async def _restore_timers(self):
        async with db.acquire() as conn: rows=await conn.fetch("SELECT h.*,e.state,e.attributes FROM native_helpers h JOIN entities e ON e.id=h.entity_ref WHERE h.helper_type='timer' AND h.enabled AND e.state='active'")
        for row in rows:
            expected=(row['attributes'] or {}).get('expected_finish')
            try: seconds=max(0,(datetime.fromisoformat(expected)-datetime.now(timezone.utc)).total_seconds())
            except Exception: continue
            if seconds: await self._timer_task(row['entity_ref'],seconds)
            else: await self._finish_timer(row['entity_ref'])
    async def _restore_schedules(self):
        async with db.acquire() as conn: rows=await conn.fetch("SELECT h.*,e.state FROM native_helpers h JOIN entities e ON e.id=h.entity_ref WHERE h.helper_type='schedule' AND h.enabled")
        for row in rows: await self._schedule_tick(row['entity_ref'])
    def _schedule_ranges(self,cfg,now):
        names=['monday','tuesday','wednesday','thursday','friday','saturday','sunday']; current=now.weekday(); active=False; transitions=[]
        blocks=cfg.get(names[current],cfg.get(str(current),[])) or []
        for block in blocks:
            if isinstance(block,str): start,end=block.split('-',1)
            else: start,end=block.get('start'),block.get('end')
            sh,sm=map(int,start.split(':')); eh,em=map(int,end.split(':')); begin=now.replace(hour=sh,minute=sm,second=0,microsecond=0); finish=now.replace(hour=eh,minute=em,second=0,microsecond=0)
            if finish<=begin: finish+=timedelta(days=1)
            if begin<=now<finish: active=True
            transitions.extend([begin,finish])
        # Include overnight blocks from yesterday.
        previous=(current-1)%7; prev=cfg.get(names[previous],cfg.get(str(previous),[])) or []
        for block in prev:
            if isinstance(block,str): start,end=block.split('-',1)
            else: start,end=block.get('start'),block.get('end')
            sh,sm=map(int,start.split(':')); eh,em=map(int,end.split(':'))
            begin=(now-timedelta(days=1)).replace(hour=sh,minute=sm,second=0,microsecond=0); finish=now.replace(hour=eh,minute=em,second=0,microsecond=0)
            if finish>begin and begin<=now<finish: active=True
        future=[x for x in transitions if x>now]
        return active,min(future) if future else now+timedelta(days=1)
    async def _schedule_tick(self,entity_ref):
        row=await self._helper(entity_ref,'schedule'); now=datetime.now(__import__('zoneinfo').zoneinfo.ZoneInfo(self.timezone_name)); active,next_at=self._schedule_ranges(row['config'] or {},now)
        state='on' if active else 'off'
        if row['state']!=state: await self._set(row,state,{'next_transition':next_at.isoformat()})
        old=self.tasks.pop(('schedule',int(entity_ref)),None)
        if old: old.cancel()
        async def wait_transition():
            try: await asyncio.sleep(max(0,(next_at-now).total_seconds())); await self._schedule_tick(entity_ref)
            except asyncio.CancelledError: pass
        task=asyncio.create_task(wait_transition()); self.tasks[('schedule',int(entity_ref))]=task; task.add_done_callback(lambda _:self.tasks.pop(('schedule',int(entity_ref)),None))
    async def _script_run(self,a,t):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT * FROM native_scripts WHERE entity_ref=$1 AND enabled',int(t))
        if not row: raise LookupError('Script not found')
        depth=int((a.inputs or {}).get('_hcm_depth',0));
        if depth>=5: raise ValueError('Script nesting limit exceeded')
        values=dict(a.inputs or {}); schema=row['input_schema'] or {}
        for name,rule in schema.items():
            rule=rule if isinstance(rule,dict) else {'type':str(rule)}
            if name not in values:
                if 'default' in rule: values[name]=rule['default']
                elif rule.get('required',False): raise ValueError(f'Missing script input: {name}')
                continue
            expected={'string':str,'number':(int,float),'integer':int,'boolean':bool}.get(rule.get('type'))
            if expected and (not isinstance(values[name],expected) or isinstance(values[name],bool) and expected is not bool): raise ValueError(f'Invalid script input: {name}')
            if rule.get('options') and values[name] not in rule['options']: raise ValueError(f'Invalid script input option: {name}')
        if not self.engine: raise LookupError('Automation Engine unavailable')
        definition={'automation_id':row['script_id'],'name':row['name'],'mode':row['mode'],'max_runs':row['max_runs'],'enabled':row['enabled'],'action_sequence':row['action_sequence'],'condition_definition':None}
        run_id=await self.engine.trigger(definition,source='script',kind='script',variables={k:v for k,v in values.items() if k!='_hcm_depth'})
        return {'run_id':str(run_id),'script_id':str(row['script_id'])}
    async def _scene_turn_on(self,a,t):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT targets FROM native_scenes WHERE entity_ref=$1 AND enabled',int(t))
        if not row: raise LookupError('Scene not found')
        result={'success':True,'partial':False,'targets':[]}
        for target in row['targets']:
            try:
                state=target.get('state'); entity=int(target['entity_ref'])
                async with db.acquire() as conn: info=await conn.fetchrow('SELECT provider_id,domain,available FROM entities WHERE id=$1',entity)
                if not info or not info['available']: raise LookupError('Target unavailable')
                service='turn_on' if state in ('on',True) else 'turn_off'; value=await self.registry.services.invoke(info['provider_id'],info['domain'],service,{},target_entity_id=entity); result['targets'].append({'entity_ref':entity,'success':True,'result':value})
            except Exception as exc: result['success']=False; result['partial']=True; result['targets'].append({'entity_ref':target.get('entity_ref'),'success':False,'error':type(exc).__name__})
        return result
    async def create_helper(self,helper_type,name,config,*,entity_id=None):
        self._validate_helper(helper_type,config); slug=entity_id or f'{helper_type}.{re.sub("[^a-z0-9]+","_",name.lower()).strip("_")}'
        if '.' not in slug: slug=f'{helper_type}.{slug}'
        device=await self.context.device('helper:'+slug,name,available=True); ref=await self.context.entity('helper:'+slug,slug,device,name,device_class=helper_type)
        initial=self._initial(helper_type,config); await self.context.state(ref,initial,attributes=config)
        async with db.acquire() as conn: row=await conn.fetchrow('INSERT INTO native_helpers(entity_ref,entity_id,name,helper_type,config) VALUES($1,$2,$3,$4,$5::jsonb) RETURNING *',ref,slug,name,helper_type,json.dumps(config))
        return dict(row)
    def _validate_helper(self,kind,cfg):
        if kind not in HELPER_TYPES: raise ValueError('Unsupported helper type')
        if kind=='input_number' and not (float(cfg.get('min',0))<=float(cfg.get('max',100)) and float(cfg.get('step',1))>0): raise ValueError('Invalid input_number configuration')
        if kind=='input_select' and (not cfg.get('options') or len(set(cfg['options']))!=len(cfg['options'])): raise ValueError('input_select options must be unique and non-empty')
        if kind=='input_text' and int(cfg.get('max_length',255))<1: raise ValueError('Invalid input_text max_length')
        if kind=='timer' and not 0<float(cfg.get('duration',0))<=86400: raise ValueError('Invalid timer duration')
    async def list_helpers(self):
        async with db.acquire() as conn:
            rows=await conn.fetch('SELECT h.*,e.state,e.attributes,e.available FROM native_helpers h JOIN entities e ON e.id=h.entity_ref ORDER BY h.entity_id')
        return [dict(r) for r in rows]
    async def get_helper(self,helper_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT h.*,e.state,e.attributes,e.available FROM native_helpers h JOIN entities e ON e.id=h.entity_ref WHERE h.helper_id=$1',UUID(str(helper_id)))
        if not row: raise LookupError('Helper not found')
        return dict(row)
    async def update_helper(self,helper_id,config):
        row=await self.get_helper(helper_id); self._validate_helper(row['helper_type'],config)
        async with db.acquire() as conn: updated=await conn.fetchrow('UPDATE native_helpers SET config=$2::jsonb,updated_at=now() WHERE helper_id=$1 RETURNING *',UUID(str(helper_id)),json.dumps(config))
        return dict(updated)

    async def delete_helper(self,helper_id):
        row=await self.get_helper(helper_id)
        async with db.acquire() as conn:
            used=await conn.fetchval("SELECT EXISTS(SELECT 1 FROM automations WHERE trigger_definitions::text LIKE $1 OR action_sequence::text LIKE $1)",f'%{row["entity_ref"]}%')
            if used: raise ValueError('Helper is referenced by an automation')
            await conn.execute('DELETE FROM native_helpers WHERE helper_id=$1',UUID(str(helper_id)))
            await conn.execute('UPDATE entities SET enabled=false WHERE id=$1',row['entity_ref'])
        return True
    async def create_script(self,name,actions,*,description=None,mode='single',max_runs=10,inputs=None,entity_id=None):
        if mode not in ('single','restart','queued','parallel') or not 1<=int(max_runs)<=10: raise ValueError('Invalid script mode')
        validator=getattr(self.engine,'store',None)
        if validator:
            for action in actions: await validator._validate_action(action)
        slug=entity_id or f'script.{re.sub("[^a-z0-9]+","_",name.lower()).strip("_")}'
        device=await self.context.device('script:'+slug,name,available=True); ref=await self.context.entity('script:'+slug,slug,device,name)
        await self.context.state(ref,'off',attributes={})
        async with db.acquire() as conn: row=await conn.fetchrow('INSERT INTO native_scripts(entity_ref,entity_id,name,description,mode,max_runs,input_schema,action_sequence) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) RETURNING *',ref,slug,name,description,mode,max_runs,json.dumps(inputs or {}),json.dumps(actions))
        return dict(row)
    async def update_script(self,script_id,body):
        row=await self.get_script(script_id); actions=body.get('actions',row['action_sequence']); validator=getattr(self.engine,'store',None)
        if validator:
            for action in actions: await validator._validate_action(action)
        async with db.acquire() as conn:
            updated=await conn.fetchrow('UPDATE native_scripts SET name=$2,description=$3,mode=$4,max_runs=$5,input_schema=$6::jsonb,action_sequence=$7::jsonb,updated_at=now() WHERE script_id=$1 RETURNING *',UUID(str(script_id)),body.get('name',row['name']),body.get('description',row['description']),body.get('mode',row['mode']),body.get('max_runs',row['max_runs']),json.dumps(body.get('inputs',row['input_schema'])),json.dumps(actions))
        return dict(updated)

    async def list_scripts(self):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT s.*,e.state,e.attributes FROM native_scripts s JOIN entities e ON e.id=s.entity_ref ORDER BY s.entity_id')
        return [dict(r) for r in rows]
    async def get_script(self,script_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT s.*,e.state,e.attributes FROM native_scripts s JOIN entities e ON e.id=s.entity_ref WHERE s.script_id=$1',UUID(str(script_id)))
        if not row: raise LookupError('Script not found')
        return dict(row)
    async def delete_script(self,script_id):
        await self.get_script(script_id)
        async with db.acquire() as conn: await conn.execute('DELETE FROM native_scripts WHERE script_id=$1',UUID(str(script_id)))
        return True
    async def create_scene(self,name,targets,*,description=None,snapshot=False,entity_id=None):
        normalized=[]
        for target in targets:
            ref=int(target['entity_ref'])
            if snapshot:
                async with db.acquire() as conn: row=await conn.fetchrow('SELECT state,attributes FROM entities WHERE id=$1 AND enabled',ref)
                if not row: raise LookupError('Scene target unavailable')
                normalized.append({'entity_ref':ref,'state':row['state'],'attributes':row['attributes'] or {}})
            else: normalized.append({'entity_ref':ref,'state':target.get('state'),'attributes':target.get('attributes',{})})
        slug=entity_id or f'scene.{re.sub("[^a-z0-9]+","_",name.lower()).strip("_")}'
        device=await self.context.device('scene:'+slug,name,available=True); ref=await self.context.entity('scene:'+slug,slug,device,name)
        await self.context.state(ref,'off',attributes={})
        async with db.acquire() as conn: row=await conn.fetchrow('INSERT INTO native_scenes(entity_ref,entity_id,name,description,targets,snapshot) VALUES($1,$2,$3,$4,$5::jsonb,$6) RETURNING *',ref,slug,name,description,json.dumps(normalized),snapshot)
        return dict(row)
    async def update_scene(self,scene_id,body):
        row=await self.get_scene(scene_id); targets=body.get('targets',row['targets'])
        normalized=[{'entity_ref':int(x['entity_ref']),'state':x.get('state'),'attributes':x.get('attributes',{})} for x in targets]
        async with db.acquire() as conn: updated=await conn.fetchrow('UPDATE native_scenes SET name=$2,description=$3,targets=$4::jsonb,updated_at=now() WHERE scene_id=$1 RETURNING *',UUID(str(scene_id)),body.get('name',row['name']),body.get('description',row['description']),json.dumps(normalized))
        return dict(updated)

    async def list_scenes(self):
        async with db.acquire() as conn: rows=await conn.fetch('SELECT s.*,e.state,e.attributes FROM native_scenes s JOIN entities e ON e.id=s.entity_ref ORDER BY s.entity_id')
        return [dict(r) for r in rows]
    async def get_scene(self,scene_id):
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT s.*,e.state,e.attributes FROM native_scenes s JOIN entities e ON e.id=s.entity_ref WHERE s.scene_id=$1',UUID(str(scene_id)))
        if not row: raise LookupError('Scene not found')
        return dict(row)
    async def delete_scene(self,scene_id):
        await self.get_scene(scene_id)
        async with db.acquire() as conn: await conn.execute('DELETE FROM native_scenes WHERE scene_id=$1',UUID(str(scene_id)))
        return True
    def _initial(self,kind,cfg):
        return {'input_boolean':'on' if cfg.get('initial',False) else 'off','input_button':None,'input_number':float(cfg.get('initial',cfg.get('min',0))),'input_text':str(cfg.get('initial','')),'input_select':cfg.get('initial',cfg.get('options',[None])[0]),'input_datetime':cfg.get('initial'), 'counter':int(cfg.get('initial',0)),'timer':'idle','schedule':'off'}[kind]
