from datetime import date, datetime
from importlib import import_module
from zoneinfo import ZoneInfo
import pytest

m=import_module('01_HCM.automation')

def test_trigger_id_is_stable_and_sun_offsets_are_normalized():
    first={'type':'time','time':'07:00'}
    assert m.trigger_id(first)==m.trigger_id(dict(first))
    assert m.AutomationStore()._offset_seconds('-00:30:00') == -1800

def test_native_sun_events_are_timezone_aware_and_ordered():
    sun=m.SunCalculator(42.3314,-83.0458,'America/Detroit')
    events=sun.events(date(2026,6,21))
    assert events['sunrise'].tzinfo is not None and events['sunset']>events['sunrise']

def test_dst_spring_skips_nonexistent_local_time():
    engine=m.AutomationEngine(object(),timezone_name='America/New_York')
    trigger={'type':'time','times':['02:30'],'trigger_id':'spring'}
    assert engine._day_occurrences(trigger,date(2026,3,8)) == []

def test_dst_fall_uses_one_occurrence_for_repeated_wall_time():
    engine=m.AutomationEngine(object(),timezone_name='America/New_York')
    trigger={'type':'time','times':['01:30'],'trigger_id':'fall'}
    values=engine._day_occurrences(trigger,date(2026,11,1))
    assert len(values)==1 and values[0].fold==0

@pytest.mark.asyncio
async def test_native_if_choose_repeat_and_parallel_actions():
    engine=m.AutomationEngine(object())
    ctx=m.RunContext({'automation_id':'a','mode':'single'},'run',[],__import__('asyncio').Event(),variables={})
    seen=[]
    async def condition(c,ctx=None): return c.get('value',False)
    async def action(ctx,a,depth=0): seen.append(a.get('marker'))
    engine.evaluate_condition=condition; engine._action=action
    await m.AutomationEngine._action(engine,ctx,{'type':'if','conditions':{'value':True},'then':[{'marker':'then'}],'else':[{'marker':'else'}]})
    await m.AutomationEngine._action(engine,ctx,{'type':'choose','choices':[{'conditions':{'value':False},'sequence':[{'marker':'wrong'}]},{'conditions':{'value':True},'sequence':[{'marker':'choice'}]}],'default':[{'marker':'default'}]})
    await m.AutomationEngine._action(engine,ctx,{'type':'repeat','count':2,'sequence':[{'marker':'repeat'}]})
    await m.AutomationEngine._action(engine,ctx,{'type':'parallel','branches':[[{'marker':'p1'}],[{'marker':'p2'}]]})
    assert seen.count('then')==1 and seen.count('choice')==1 and seen.count('repeat')==2 and {'p1','p2'} <= set(seen)

def test_numeric_state_trigger_crossing_semantics():
    engine=m.AutomationEngine(object())
    trigger={'type':'numeric_state','entity_ref':1,'above':70}
    event=lambda previous,current:{'event_type':'entity.state_changed','entity_id':1,'payload':{'previous_state':str(previous),'state':str(current)}}
    assert engine._trigger_matches(trigger,event(69,71))
    assert not engine._trigger_matches(trigger,event(71,72))
    assert engine._trigger_matches(trigger,event(69,71))
