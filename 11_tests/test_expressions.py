import pytest
from datetime import datetime, timezone
from importlib import import_module

m=import_module('01_HCM.expressions')

async def resolver(entity_id):
    return {'sensor.foo':m.Snapshot(1,'sensor.foo',72.5,{'temperature':72.5}), 'binary_sensor.bar':m.Snapshot(2,'binary_sensor.bar','on',{})}.get(entity_id)

@pytest.fixture
def engine(): return m.ExpressionEngine(resolver=resolver,timezone_name='UTC')

@pytest.mark.asyncio
async def test_typed_jinja_filters_and_mixed_template(engine):
    assert await engine.evaluate("{{ states('sensor.foo') | float(0) }}",syntax='jinja') == 72.5
    assert await engine.evaluate("Current {{ states('sensor.foo') }}",syntax='jinja') == 'Current 72.5'
    assert await engine.evaluate("{{ is_state('binary_sensor.bar','on') and (states('sensor.foo') | float > 70) }}",syntax='jinja') is True

@pytest.mark.asyncio
async def test_safe_trigger_access_and_dependencies(engine):
    compiled=engine.compile("{{ trigger.to_state.state }}",syntax='jinja')
    assert await engine.evaluate_compiled(compiled,{'trigger':{'to_state':{'state':'on'}}})=='on'
    assert engine.dependencies(engine.compile("states('sensor.foo') | float",syntax='native')) == ['sensor.foo']

@pytest.mark.asyncio
async def test_undefined_default_and_datetime(engine):
    assert await engine.evaluate("unknown | default('x')")=='x'
    assert await engine.evaluate("as_timestamp(utcnow()) > 0") is True

@pytest.mark.asyncio
async def test_security_and_limits(engine):
    for source in ("__class__", "open('x')", "__import__('os')", "x.__dict__", "eval('1')"):
        with pytest.raises(m.ExpressionError): engine.compile(source)
    with pytest.raises(m.ExpressionError): engine.compile('1+'+'1'*5000)
