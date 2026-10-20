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
