import pytest
from importlib import import_module
from types import SimpleNamespace

controls = import_module('01_HCM.writable_controls')
primitives = import_module('01_HCM.primitives')
importer = import_module('01_HCM.ha_importer')


def test_number_capability_validates_bounds_and_step():
    cap=controls.NumberCapability(minimum=0, maximum=10, step=0.5)
    assert controls.validate_number(2.5,cap)==2.5
    for value in (-1, 11, 2.25):
        with pytest.raises(ValueError, match='INVALID_ARGUMENT'):
            controls.validate_number(value,cap)


def test_select_capability_rejects_unknown_option():
    cap=controls.SelectCapability(options=('auto','manual'))
    assert controls.validate_option('manual',cap)=='manual'
    with pytest.raises(ValueError, match='INVALID_ARGUMENT'):
        controls.validate_option('other',cap)


@pytest.mark.asyncio
async def test_system_log_dry_run_and_redaction():
    p=primitives.NativePrimitives(None)
    planned=await p._system_log(SimpleNamespace(message='token=synthetic',severity='info',category=None,dry_run=True),None)
    assert planned['status']=='dry_run'
    result=await p._system_log(SimpleNamespace(message='token=synthetic',severity='info',category='test',dry_run=False),None)
    assert result['status']=='success' and 'synthetic' not in str(result)


def test_low_risk_service_mappings_are_explicit():
    assert importer.SERVICE_MAPPINGS['number.set_value']['domain']=='number'
    assert importer.SERVICE_MAPPINGS['select.select_option']['service']=='select_option'
    assert importer.SERVICE_MAPPINGS['automation.toggle']['service']=='toggle'
    assert importer.SERVICE_MAPPINGS['system_log.write']['service']=='log'


def test_system_log_import_normalizes_fields():
    plan=importer.analyze_home_assistant({'automations':[{'id':'log','actions':[{
        'service':'system_log.write','data':{'message':'hello','level':'warning','logger':'test'}}]}]})
    node=plan['items'][0]['nested'][2]['children'][0]
    assert node['status']=='TRANSLATED'
    assert node['native']['service_data']=={'message':'hello','severity':'warning','category':'test'}
