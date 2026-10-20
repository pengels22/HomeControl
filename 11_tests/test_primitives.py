import pytest
from importlib import import_module

m=import_module('01_HCM.primitives')

def test_helper_validation_and_initial_values():
    manager=m.NativePrimitives(None)
    assert manager._initial('input_boolean',{'initial':True})=='on'
    assert manager._initial('input_select',{'options':['A','B']})=='A'
    manager._validate_helper('input_number',{'min':0,'max':10,'step':1})
    with pytest.raises(ValueError): manager._validate_helper('input_select',{'options':['A','A']})
    with pytest.raises(ValueError): manager._validate_helper('timer',{'duration':0})

def test_native_service_models_reject_unknown_fields():
    with pytest.raises(Exception): m.NumberArg(value=1,bad=True)
    assert m.ScriptArg(inputs={'message':'ok'}).inputs['message']=='ok'

@pytest.mark.asyncio
async def test_scene_translation_reports_supported_and_unsupported_attributes(monkeypatch):
    class Conn:
        async def fetchrow(self,query,*args):
            if 'FROM entities' in query: return {'id':1,'entity_id':'light.test','provider_id':'mock','domain':'light','available':True}
    class Acquire:
        async def __aenter__(self): return Conn()
        async def __aexit__(self,*args): pass
    class Registry:
        async def inspect(self,kind,provider_id=None):
            return [{'domain':'light','service_name':'turn_on','argument_schema':{}},{'domain':'light','service_name':'set_level','argument_schema':{}}]
    monkeypatch.setattr(m.db,'acquire',lambda:Acquire())
    plan=await m.NativePrimitives(Registry())._scene_plan_target({'entity_ref':1,'state':'on','attributes':{'brightness':55,'color_temp':3000}})
    assert [x['service'] for x in plan['operations']]==['turn_on','set_level']
    assert plan['unsupported_attributes']==['color_temp']
