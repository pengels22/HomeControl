"""Real PostgreSQL regressions; each test owns a disposable schema."""
import os
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from importlib import import_module
import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

registry = import_module('01_HCM.channel_registry')
api = import_module('01_HCM.metadata_api')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def database(monkeypatch):
    url = os.getenv('HCM_TEST_DATABASE_URL')
    if not url:
        pytest.skip('HCM_TEST_DATABASE_URL required for PostgreSQL integration tests')
    conn = await asyncpg.connect(url)
    schema = 'metadata_test_' + uuid.uuid4().hex
    await conn.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
    await conn.execute(f'CREATE SCHEMA {schema}')
    await conn.execute(f'SET search_path TO {schema},public')
    try:
        await conn.execute((ROOT / '08_database/schema.sql').read_text())
        # Pre-existing rooms, bindings and auth survive the forward migration.
        await conn.execute("INSERT INTO rooms(id,name) VALUES(901,'Existing HVAC Room')")
        await conn.execute("INSERT INTO room_hvac(room_id,temperature_f) VALUES(901,70)")
        await conn.execute("INSERT INTO users(username,role,password_hash) VALUES('preserve','ADMIN','test-verifier')")
        await conn.execute((ROOT / '08_database/008_channel_metadata.sql').read_text())
        @asynccontextmanager
        async def acquire():
            yield conn
        monkeypatch.setattr(registry.db,'acquire',acquire)
        yield conn
    finally:
        await conn.execute('SET search_path TO public')
        await conn.execute(f'DROP SCHEMA {schema} CASCADE')
        await conn.close()


async def module(conn,kind,number):
    return await conn.fetchval('INSERT INTO modules(module_type,hostname,ip_address,device_id) VALUES($1,$2,$3,$4) RETURNING id',kind,f'{kind}{number}',f'192.0.2.{number}',f'0200000000{number:02x}')


async def test_database_defaults_and_locked_identity(database):
    rcm = await module(database,'RCM',1)
    lcm = await module(database,'LCM',2)
    assert await database.fetchval('SELECT count(*) FROM channel_metadata WHERE module_id=$1 AND purpose=\'GENERAL\'',rcm) == 32
    assert await database.fetchval('SELECT count(*) FROM channel_metadata WHERE module_id=$1 AND purpose=\'LIGHTING\'',lcm) == 22
    assert not await database.fetchval('SELECT bool_or(mqtt_enabled OR matter_enabled) FROM channel_metadata')
    for sql in [
        "UPDATE channel_metadata SET purpose='GENERAL' WHERE channel_kind='lv_dimmer'",
        "UPDATE channel_metadata SET purpose='GENERAL' WHERE channel_kind='hv_dimmer'",
        "UPDATE channel_metadata SET channel_kind='relay' WHERE channel_kind='hv_dimmer'",
        "UPDATE channel_metadata SET emergency=true WHERE purpose='GENERAL'",
        "UPDATE channel_metadata SET hvac_control='R' WHERE purpose='GENERAL'",
    ]:
        with pytest.raises(asyncpg.PostgresError):
            async with database.transaction():
                await database.execute(sql)
    assert await database.fetchval('SELECT temperature_f FROM room_hvac WHERE room_id=901') == 70
    assert await database.fetchval("SELECT password_hash FROM users WHERE username='preserve'") == 'test-verifier'


async def test_rooms_panel_membership_and_rename(database):
    await module(database,'LCM',1)
    panel=await module(database,'PNL',2)
    rows=await registry.channels()
    channel=rows[0]
    await registry.update_channel(channel['id'],{'room_id':901},'test')
    await database.execute('INSERT INTO pnl_rooms(module_id,room_id,is_primary) VALUES($1,901,true)',panel)
    controls=await registry.pnl_controls('PNL2')
    assert len(controls)==1 and not controls[0]['mqtt_enabled'] and not controls[0]['matter_enabled']
    await database.execute("UPDATE rooms SET name='Renamed' WHERE id=901")
    assert (await registry.pnl_controls('PNL2'))[0]['room_name']=='Renamed'
    await registry.update_channel(channel['id'],{'room_id':None},'test')
    assert await registry.pnl_controls('PNL2')==[]


async def test_emergency_and_hvac_fields_transactional(database):
    await module(database,'RCM',1)
    c=(await registry.channels())[0]
    await registry.update_channel(c['id'],{'purpose':'LIGHTING','emergency':True},'test')
    with pytest.raises(ValueError):
        await registry.update_channel(c['id'],{'purpose':'GENERAL'},'test')
    assert (await registry.channels())[0]['emergency']
    await registry.update_channel(c['id'],{'purpose':'HVAC','hvac_control':'G','emergency':False},'test')
    with pytest.raises(ValueError):
        await registry.update_channel(c['id'],{'hvac_control':'R'},'test')
    assert (await registry.channels())[0]['hvac_control']=='G'


async def test_endpoint_persistence_and_no_renumber(database):
    await module(database,'LCM',1)
    a,b=(await registry.channels())[:2]
    for c in [a,b]:
        await registry.update_channel(c['id'],{'matter_enabled':True,'mqtt_enabled':True},'test')
    await registry.allocate_endpoints()
    before={r['id']:r['endpoint'] for r in await registry.channels()}
    await registry.update_channel(a['id'],{'display_name':'Renamed','matter_enabled':False},'test')
    await registry.allocate_endpoints()
    assert {r['id']:r['endpoint'] for r in await registry.channels()} == before
    await registry.update_channel(a['id'],{'matter_enabled':True},'test')
    await registry.allocate_endpoints()
    assert {r['id']:r['endpoint'] for r in await registry.channels()} == before
    assert (await registry.channels())[0]['mqtt_enabled'] is True


async def test_metadata_api_auth_validation(database):
    await module(database,'LCM',1)
    app=FastAPI();app.include_router(api.router)
    identity={'user':'test','role':'READONLY'}
    app.dependency_overrides[api.require_user]=lambda:identity
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/v1/rooms')).status_code==200
        rows=(await client.get('/api/v1/channels')).json()
        assert (await client.post('/api/v1/rooms',json={'name':'Denied'})).status_code==403
        assert (await client.patch(f"/api/v1/channels/{rows[0]['id']}",json={'display_name':'Denied'})).status_code==403
        identity['role']='ADMIN'
        assert (await client.post('/api/v1/rooms',json={'name':'Allowed'})).status_code==200
        dimmer=next(r for r in rows if r['channel_kind']=='lv_dimmer')
        assert (await client.patch(f"/api/v1/channels/{dimmer['id']}",json={'purpose':'GENERAL'})).status_code==422
        assert (await client.patch(f"/api/v1/channels/{rows[0]['id']}",json={'display_name':'Allowed'})).status_code==200
        assert (await client.patch(f"/api/v1/channels/{rows[0]['id']}",json={'channel_kind':'hv_dimmer'})).status_code==422


async def test_module_removal_keeps_endpoint_tombstone(database):
    module_id=await module(database,'LCM',1)
    channel=(await registry.channels())[0]
    await registry.update_channel(channel['id'],{'matter_enabled':True},'test')
    await registry.allocate_endpoints()
    endpoint=(await registry.channels())[0]['endpoint']
    await database.execute('DELETE FROM modules WHERE id=$1',module_id)
    assert await database.fetchval('SELECT endpoint FROM matter_endpoints WHERE channel_id IS NULL')==endpoint
    await module(database,'LCM',2)
    new=(await registry.channels())[0]
    await registry.update_channel(new['id'],{'matter_enabled':True},'test')
    await registry.allocate_endpoints()
    assert (await registry.channels())[0]['endpoint']>endpoint


async def test_role_change_preserves_history_and_seeds_new_profile(database):
    module_id=await module(database,'RCM',1)
    await database.execute("UPDATE modules SET module_type='LCM' WHERE id=$1",module_id)
    records=await registry.channels()
    assert len([r for r in records if r['enabled']])==22
    assert all(not r['enabled'] for r in records if r['channel_id']=='B1')


async def test_new_lighting_appears_without_bridge_flags(database):
    panel=await module(database,'PNL',1)
    await database.execute('INSERT INTO pnl_rooms(module_id,room_id,is_primary) VALUES($1,901,true)',panel)
    assert await registry.pnl_controls('PNL1')==[]
    await module(database,'LCM',2)
    channel=(await registry.channels())[0]
    await registry.update_channel(channel['id'],{'room_id':901},'test')
    assert len(await registry.pnl_controls('PNL1'))==1
    await registry.update_channel(channel['id'],{'purpose':'GENERAL'},'test')
    assert await registry.pnl_controls('PNL1')==[]


async def test_legacy_file_import_preserves_unbound_names_and_emergency(database,monkeypatch,tmp_path):
    import json
    storage=import_module('01_HCM.storage')
    await module(database,'LCM',1)
    path=tmp_path/'config'/'LCM'/'LCM1.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'config':{'channels':[{'channel':'A1','name':'Legacy Light','emergency_lighting':True,'mqtt_enabled':True}]}}))
    monkeypatch.setattr(storage,'storage_root',lambda:tmp_path)
    await registry.import_legacy_configuration(database)
    channel=next(r for r in await registry.channels() if r['channel_id']=='A1')
    assert channel['display_name']=='Legacy Light' and channel['emergency'] and channel['mqtt_enabled']


async def test_hvac_room_id_survives_rename_and_disabled_room_stays_disabled(database):
    from unittest.mock import AsyncMock
    hvac=import_module('01_HCM.hvac')
    controller=hvac.HVACController(AsyncMock(),AsyncMock())
    reading=hvac.RoomReading('Old cached name',69,True,room_id=901)
    await database.execute("UPDATE rooms SET name='New name' WHERE id=901")
    await controller.persist_room(reading)
    assert reading.room=='New name' and reading.room_id==901
    assert await database.fetchval('SELECT count(*) FROM rooms')==1
    await database.execute('UPDATE rooms SET enabled=false WHERE id=901')
    with pytest.raises(ValueError,match='disabled'):
        await controller.persist_room(reading)
    assert not await database.fetchval('SELECT enabled FROM rooms WHERE id=901')


async def test_reconciliation_does_not_consume_existing_endpoint_numbers(database):
    await module(database,'LCM',1)
    channel=(await registry.channels())[0]
    await registry.update_channel(channel['id'],{'matter_enabled':True},'test')
    await registry.allocate_endpoints()
    first=await database.fetchval('SELECT last_value FROM matter_endpoints_endpoint_seq')
    for _ in range(5): await registry.allocate_endpoints()
    assert await database.fetchval('SELECT last_value FROM matter_endpoints_endpoint_seq')==first
