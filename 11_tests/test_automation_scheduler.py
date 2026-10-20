from datetime import date, datetime
from importlib import import_module
from zoneinfo import ZoneInfo

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
