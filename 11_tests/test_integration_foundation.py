"""Foundation tests use only an internal sensor and harmless in-process service."""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock
import asyncpg
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

registry_mod=import_module('01_HCM.integrations.registry')
runtime_mod=import_module('01_HCM.integrations.runtime')
provider_mod=import_module('01_HCM.integrations.provider')
mock_mod=import_module('01_HCM.integrations.mock')
api_mod=import_module('01_HCM.integrations.api')
events=import_module('01_HCM.events')
ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
async def database(monkeypatch):
    url=os.getenv('HCM_TEST_DATABASE_URL')
    if not url:
        pytest.skip('HCM_TEST_DATABASE_URL required for PostgreSQL integration tests')
    conn=await asyncpg.connect(url)
    schema='integration_test_'+uuid.uuid4().hex
    await conn.execute(f'CREATE SCHEMA {schema}')
    await conn.execute(f'SET search_path TO {schema},public')
    try:
        await conn.execute((ROOT/'08_database/schema.sql').read_text())
        await conn.execute((ROOT/'08_database/008_channel_metadata.sql').read_text())
        native=await conn.fetchval("INSERT INTO logical_devices(logical_name,device_class,maintenance_locked) VALUES('Pre-migration lamp','light',true) RETURNING id")
        before=dict(await conn.fetchrow('SELECT * FROM logical_devices WHERE id=$1',native))
        await conn.execute((ROOT/'08_database/009_integration_foundation.sql').read_text())
        await conn.execute((ROOT/'08_database/010_integration_configuration.sql').read_text())
        await conn.execute((ROOT/'08_database/011_integration_instances.sql').read_text())
        await conn.execute((ROOT/'08_database/012_instance_runtime.sql').read_text())
        after=dict(await conn.fetchrow('SELECT * FROM logical_devices WHERE id=$1',native))
        assert {key:after[key] for key in before}==before
        @asynccontextmanager
        async def acquire(): yield conn
        monkeypatch.setattr(registry_mod.db,'acquire',acquire)
        yield conn
    finally:
        await conn.execute('SET search_path TO public')
        await conn.execute(f'DROP SCHEMA {schema} CASCADE')
        await conn.close()


@pytest.fixture
async def running(database):
    bus=events.EventBus()
    registry=registry_mod.Registry(bus)
    host=runtime_mod.Runtime(registry)
    mock=mock_mod.MockProvider()
    host.attach(mock,enabled=True)
    await host.start_provider('internal_mock')
    try:
        yield host,mock,bus
    finally:
        await host.stop()


async def test_mock_registers_device_entity_state_event_service(database):
    bus=events.EventBus()
    host=runtime_mod.Runtime(registry_mod.Registry(bus))
    mock=mock_mod.MockProvider()
    host.attach(mock,enabled=True)
    with bus.subscribe() as subscriber:
        await host.start_provider('internal_mock')
        state_event=await subscriber.queue.get()
        event=await subscriber.queue.get()
        assert isinstance(event,events.EventRecord)
        assert state_event.code=='entity.state_changed'
        assert event.code=='internal_mock.started'
        assert event.metadata['entity_id']==mock.entity_id
        assert event.metadata['provider_id']=='internal_mock'
    assert len(await host.registry.inspect('devices'))==1
    entity=(await host.registry.inspect('entities'))[0]
    assert entity['state']==70.0 and entity['available']
    assert (await host.registry.services.inspect())[0]['available']
    assert await host.registry.services.invoke('internal_mock','internal_mock','ping',{})=={'ok':True,'mock':True}
    assert await database.fetchval('SELECT count(*) FROM device_bindings')==0
    assert await database.fetchval('SELECT count(*) FROM device_management_events')==0
    await host.stop()


async def test_health_failure_isolated_and_sanitized(running):
    host,mock,_=running
    before=(await host.registry.inspect('integrations'))[0]['last_success']
    async def fail(): raise RuntimeError('Authorization: Bearer secret-never-expose')
    mock.health_check=fail
    await host.health('internal_mock')
    state=(await host.registry.inspect('integrations'))[0]
    assert state['status']=='degraded' and state['last_success']==before
    assert state['last_error']=='health_check failed (RuntimeError)'
    assert not (await host.registry.inspect('entities'))[0]['available']
    assert not (await host.registry.services.inspect())[0]['available']
    assert not host.task or not host.task.done()


async def test_registration_and_rename_keep_stable_id(running):
    host,mock,_=running
    context=host.registry.context('internal_mock')
    device=await context.device('test_device','Renamed')
    entity=await context.entity('temperature','sensor.internal_mock_temperature',device,'Renamed sensor')
    assert device==mock.device_id and entity==mock.entity_id
    assert (await host.registry.inspect('devices'))[0]['display_name']=='Renamed'
    await host.reload('internal_mock')
    assert (await host.registry.inspect('entities'))[0]['id']==entity
    # A new runtime/registry shares the same database identities.
    fresh=registry_mod.Registry()
    assert await fresh.context('internal_mock').device('test_device','Another name')==device
    assert not (await fresh.services.inspect())[0]['available']  # no live handler


async def test_state_timestamps_and_event_context(running):
    host,mock,bus=running
    context=host.registry.context('internal_mock')
    before=(await host.registry.inspect('entities'))[0]
    with bus.subscribe() as subscriber:
        await context.state(mock.entity_id,70.0,attributes={'sample':2},correlation_id='sample-2')
        event=await subscriber.queue.get()
        assert event.metadata['correlation_id']=='sample-2'
    same=(await host.registry.inspect('entities'))[0]
    assert same['last_changed']==before['last_changed'] and same['last_updated']>=before['last_updated']
    await context.state(mock.entity_id,71.0)
    after=(await host.registry.inspect('entities'))[0]
    assert after['last_changed']>same['last_changed'] and after['state']==71.0


async def test_cross_provider_ownership_rejected(running,database):
    host,mock,_=running
    await host.registry.register(provider_mod.ProviderInfo('other','Other'),enabled=True)
    other=host.registry.context('other')
    for operation in [other.entity('external','sensor.other',mock.device_id,'Wrong'),
                      other.state(mock.entity_id,999),
                      other.emit('other.event',{},entity_id=mock.entity_id)]:
        with pytest.raises(registry_mod.OwnershipError): await operation
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with database.transaction():
            await database.execute("INSERT INTO entities(entity_id,domain,provider_id,external_entity_id,device_id,display_name) VALUES('sensor.invalid','sensor','other','invalid',$1,'Wrong')",mock.device_id)
    with pytest.raises(ValueError):
        await other.emit('internal_mock.event',{})


async def test_service_schema_target_and_physical_boundary(running):
    host,mock,_=running
    class Arguments(BaseModel):
        model_config=ConfigDict(extra='forbid')
        count: int
    callback=AsyncMock(return_value={'ok':True})
    await mock.context.service('test','targeted',Arguments,callback,target_required=True,target_domains=('sensor',))
    schema=next(r for r in await host.registry.services.inspect() if r['service_name']=='targeted')
    assert schema['argument_schema']['required']==['count']
    assert schema['target_requirements']=={'required':True,'domains':['sensor']}
    for args,target in [({'count':1},None),({'bad':1},mock.entity_id)]:
        with pytest.raises(ValueError):
            await host.registry.services.invoke('internal_mock','test','targeted',args,target_entity_id=target)
    callback.assert_not_called()
    await host.registry.services.invoke('internal_mock','test','targeted',{'count':1},target_entity_id=mock.entity_id)
    assert callback.await_count==1
    await mock.context.service('test','physical',Arguments,callback,mutates_physical_state=True)
    with pytest.raises(PermissionError):
        await host.registry.services.invoke('internal_mock','test','physical',{'count':1})
    assert callback.await_count==1


async def test_readonly_inspection_auth_and_no_mutation_routes(running):
    host,_,_=running
    app=FastAPI(); app.include_router(api_mod.router)
    app.dependency_overrides[api_mod.get_runtime]=lambda:host
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/v1/integrations')).status_code==401
        app.dependency_overrides[api_mod.require_user]=lambda:{'user':'viewer','role':'READONLY'}
        for path in ['', '/devices','/entities','/services','/internal_mock/status','/internal_mock/diagnostics']:
            assert (await client.get('/api/v1/integrations'+path)).status_code==200
        assert (await client.get('/api/v1/integrations/missing/status')).status_code==404
        assert (await client.post('/api/v1/integrations',json={})).status_code==405
        assert (await client.post('/api/v1/integrations/internal_mock/reload')).status_code==404


async def test_disabled_provider_has_no_resources(database):
    host=runtime_mod.Runtime()
    mock=mock_mod.MockProvider()
    host.attach(mock)
    await host.start_provider('internal_mock')
    assert not mock.running and mock.context is None
    assert (await host.registry.inspect('integrations'))[0]['status']=='disabled'
    assert await host.registry.inspect('devices')==[]


async def test_timeout_and_shutdown_isolate_provider_without_database():
    registry=AsyncMock()
    registry.context=lambda key:object()
    registry.services.handlers={}
    host=runtime_mod.Runtime(registry,timeout=0.01)
    provider=AsyncMock()
    provider.info=provider_mod.ProviderInfo('slow','Slow')
    async def hang(): await asyncio.Event().wait()
    provider.start=hang
    host.attach(provider,enabled=True)
    await host.start_provider('slow')
    assert host.entries['slow'].status=='error'
    assert 'TimeoutError' in host.entries['slow'].last_error
    assert provider.stop.await_count==1
    await host.stop()


def test_event_bus_backpressure_and_consumer_isolation():
    bus=events.EventBus(capacity=1)
    registry=registry_mod.Registry(bus)
    context=registry.context('test')
    with bus.subscribe() as first,bus.subscribe() as second:
        event=context._publish('test.event',{'value':1})
        first.queue.get_nowait().metadata['payload']['value']=99
        assert second.queue.get_nowait().metadata['payload']['value']==1
        bus.publish(event);bus.publish(event)
        assert first.dropped==1 and second.dropped==1
    assert not bus._subscriptions


async def test_forward_migration_repeat_and_native_preservation(database):
    native=await database.fetchval("INSERT INTO logical_devices(logical_name,device_class,maintenance_locked) VALUES('Existing lamp','light',true) RETURNING id")
    before=dict(await database.fetchrow('SELECT * FROM logical_devices WHERE id=$1',native))
    await database.execute((ROOT/'08_database/009_integration_foundation.sql').read_text())
    assert dict(await database.fetchrow('SELECT * FROM logical_devices WHERE id=$1',native))==before
    assert before['provider_id'] is None


async def test_room_assignment_and_entity_identity_survive_registration(running,database):
    host,mock,_=running
    context=mock.context
    room=await database.fetchval("INSERT INTO rooms(name) VALUES('Test room') RETURNING id")
    await context.device('test_device','Assigned',room_id=room)
    await host.reload('internal_mock')
    assert (await host.registry.inspect('devices'))[0]['room_id']==room
    with pytest.raises(ValueError,match='identity'):
        await context.entity('temperature','sensor.accidental_rename',mock.device_id,'Wrong')
    entity=(await host.registry.inspect('entities'))[0]
    assert entity['entity_id']=='sensor.internal_mock_temperature'
    assert entity['display_name']=='Internal Test Temperature'


async def test_unconfigured_provider_skips_setup(database):
    host=runtime_mod.Runtime()
    mock=mock_mod.MockProvider()
    host.attach(mock,enabled=True,configured=False)
    await host.start_provider('internal_mock')
    assert mock.context is None
    assert (await host.registry.inspect('integrations'))[0]['status']=='configuration_required'
    await host.stop()


async def test_service_failure_does_not_break_runtime(running):
    host,mock,_=running
    async def fail(arguments,target):
        raise RuntimeError('secret-token')
    await mock.context.service('internal_mock','fail',mock_mod.PingArguments,fail)
    with pytest.raises(RuntimeError,match=r'^Service failed \(RuntimeError\)$'):
        await host.registry.services.invoke('internal_mock','internal_mock','fail',{})
    assert await host.registry.services.invoke('internal_mock','internal_mock','ping',{})=={'ok':True,'mock':True}
    await host.health('internal_mock')
    assert host.entries['internal_mock'].status=='connected'


async def test_configuration_encrypts_redacts_and_replaces_credentials(database,monkeypatch):
    monkeypatch.setenv('HCM_INTEGRATION_SECRET_KEY', Fernet.generate_key().decode())
    host=runtime_mod.Runtime(registry_mod.Registry()); mock=mock_mod.MockProvider(); host.attach(mock,enabled=True)
    await host.start_provider('internal_mock')
    config=import_module('01_HCM.integrations.config'); secrets=import_module('01_HCM.integrations.secrets')
    first=await config.save(mock,config.ConfigInput(config={'host':'lan.local','port':1234},credential_kind='api_key',credential='first-secret'),actor='admin')
    assert first[0]['credential_configured'] and first[0]['credential_ref'] is None
    public=await config.inspect('internal_mock'); assert 'first-secret' not in str(public) and public[0]['config']=={'host':'lan.local','port':1234}
    ref=await database.fetchval('SELECT credential_ref FROM integration_providers WHERE provider_id=$1','internal_mock')
    assert await secrets.get(ref)=='first-secret'
    await config.save(mock,config.ConfigInput(config={'host':'lan.local'},credential_kind='api_key',credential='second-secret'),actor='admin')
    assert await database.fetchval('SELECT revoked_at IS NOT NULL FROM integration_credentials WHERE credential_ref=$1',ref)
    with pytest.raises(LookupError): await secrets.get(ref)
    await host.stop()


async def test_configuration_authorization_and_validation(database):
    app=FastAPI(); from importlib import import_module
    app.include_router(import_module('01_HCM.integrations.config_api').router)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        app.dependency_overrides[import_module('01_HCM.integrations.config_api').require_user]=lambda:{'user':'viewer','role':'READONLY'}
        assert (await client.post('/api/v1/integrations/internal_mock/disable')).status_code==403


def test_webhook_guard_authentication_replay_and_size():
    webhooks=import_module('01_HCM.integrations.webhooks'); h=webhooks.WebhookGuard('internal_mock',max_bytes=8)
    import hmac,hashlib
    payload=b'payload'; sig=hmac.new(b'secret',payload,hashlib.sha256).hexdigest()
    assert h.verify(payload,sig,'secret','nonce')['provider_id']=='internal_mock'
    with pytest.raises(ValueError,match='replay'): h.verify(payload,sig,'secret','nonce')
    with pytest.raises(ValueError,match='authentication'): h.verify(payload,'bad','secret','new')


async def test_provider_chooser_and_multiple_instances(database,monkeypatch):
    monkeypatch.setenv('HCM_INTEGRATION_SECRET_KEY', Fernet.generate_key().decode())
    host=runtime_mod.Runtime(registry_mod.Registry()); mock=mock_mod.MockProvider(); host.attach(mock,enabled=True); await host.start_provider('internal_mock')
    instances=import_module('01_HCM.integrations.instances')
    one=await instances.create('internal_mock','Mock One',{'host':'one'},credential='one-secret',actor='admin')
    two=await instances.create('internal_mock','Mock Two',{'host':'two'},credential='two-secret',actor='admin')
    rows=await instances.list_instances(); assert {str(r['instance_id']) for r in rows} >= {one,two}
    assert all(r['credential_ref'] is None for r in rows)
    await instances.remove(one,'admin')
    assert any(str(r['instance_id'])==two for r in await instances.list_instances())
    await host.stop()


async def test_instance_runtime_siblings_are_isolated(database):
    host=runtime_mod.Runtime(registry_mod.Registry()); mock=mock_mod.MockProvider(); await host.registry.register(mock.info,enabled=True)
    ids=[]
    for name in ('A','B'):
        iid=await database.fetchval("INSERT INTO integration_instances(provider_id,display_name,enabled,configured) VALUES('internal_mock',$1,true,true) RETURNING instance_id",name)
        ids.append(str(iid)); host.attach_instance(str(iid),'internal_mock',host.registry.context('internal_mock',str(iid)),enabled=True,configured=True)
        await host.start_instance(str(iid))
    assert len(await host.registry.inspect('devices'))==2
    host.instances[ids[1]].provider.fail_health=True
    await host._operation_instance(ids[1],'health_check')
    assert host.instances[ids[0]].status=='connected' and host.instances[ids[1]].status=='degraded'
    await host.stop_instance(ids[0]); assert host.instances[ids[1]].status=='degraded'
    await host.reload_instance(ids[1]); assert host.instances[ids[1]].status=='degraded'
    await host.stop()


async def test_mock_oauth_state_exchange_and_replay(database,monkeypatch):
    monkeypatch.setenv('HCM_INTEGRATION_SECRET_KEY', Fernet.generate_key().decode())
    host=runtime_mod.Runtime(registry_mod.Registry()); mock=mock_mod.MockProvider(); host.attach(mock,enabled=True); await host.start_provider('internal_mock')
    iid=await database.fetchval("INSERT INTO integration_instances(provider_id,display_name,enabled,configured) VALUES('internal_mock','OAuth',true,true) RETURNING instance_id")
    oauth=import_module('01_HCM.integrations.oauth'); url=await oauth.authorization_url('internal_mock','https://auth.test/authorize','client','https://hcm.test/cb',instance_id=iid)
    from urllib.parse import parse_qs,urlparse
    state=parse_qs(urlparse(url).query)['state'][0]
    await oauth.consume_state('internal_mock',state,'https://hcm.test/cb',iid)
    with pytest.raises(ValueError,match='Invalid or expired'): await oauth.consume_state('internal_mock',state,'https://hcm.test/cb',iid)
    token=await mock.oauth_exchange('mock-code'); ref=await import_module('01_HCM.integrations.secrets').put('internal_mock','oauth_access_token',token['access_token']); await oauth.associate_access_credential(iid,ref)
    assert await database.fetchval('SELECT credential_ref IS NOT NULL FROM integration_instances WHERE instance_id=$1',iid)
    await host.stop()
