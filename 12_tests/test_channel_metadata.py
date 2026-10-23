from importlib import import_module
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest

contract = import_module('08_servises.common.channel_metadata')
bridges = import_module('01_HCM.bridges')
entities = import_module('01_HCM.entities')
registry = import_module('01_HCM.channel_registry')
hvac = import_module('01_HCM.hvac')
rcm = import_module('04_RCM.main')


@pytest.mark.parametrize('values', [
    {'emergency': True}, {'hvac_control': 'G'}, {'purpose': 'HVAC'},
    {'purpose': 'HVAC', 'hvac_control': 'R'}, {'security_endpoint_label': 'Door'},
    {'other_function': 'Custom'}, {'hvac_description': 'Custom'},
    {'purpose': 'EMERGENCY_LIGHTING'},
])
def test_illegal_semantics_rejected(values):
    with pytest.raises(ValueError):
        contract.ChannelMetadata(**values)


@pytest.mark.parametrize('kind', ['lv_dimmer', 'hv_dimmer'])
def test_dimmer_purpose_locked(kind):
    with pytest.raises(ValueError):
        contract.validate_metadata('LCM', kind, {'purpose': 'GENERAL'})
    assert contract.validate_metadata('LCM', kind, {'purpose': 'LIGHTING'}).purpose == 'LIGHTING'


@pytest.mark.parametrize('values', [
    {'purpose': 'LIGHTING', 'emergency': True},
    {'purpose': 'SECURITY', 'security_endpoint_label': 'Front Door Strike'},
    {'purpose': 'OTHER', 'other_function': 'Fountain'},
    {'purpose': 'HVAC', 'hvac_control': 'OTHER_HVAC', 'hvac_description': 'Dehumidifier'},
])
def test_valid_semantics(values):
    assert contract.ChannelMetadata(**values).model_dump(mode='json').items() >= values.items()


def row(**values):
    return {'id': 1, 'channel_id': 'A1', 'hostname': 'RCM01', 'display_name': 'Kitchen',
            'purpose': 'LIGHTING', 'channel_kind': 'relay', 'enabled': True, 'mqtt_enabled': False,
            'matter_enabled': False, 'logical_device_id': 2, 'endpoint': 4, **values}


@pytest.mark.parametrize('bridge', ['mqtt', 'matter'])
def test_opt_in_stable_projection(bridge):
    assert bridges.projection([row()], bridge)[0]['kind'] is None
    a = bridges.projection([row(**{f'{bridge}_enabled': True})], bridge)[0]
    b = bridges.projection([row(display_name='Renamed', room_name='Other', **{f'{bridge}_enabled': True})], bridge)[0]
    assert a['stable_id'] == b['stable_id'] == 'logical_2'
    assert a['endpoint'] == b['endpoint'] == 4
    assert b['name'] == 'Renamed'
    assert b['room'] == 'Other'


@pytest.mark.parametrize('kind,expected', [('relay', 'light'), ('lv_dimmer', 'dimmer'), ('hv_dimmer', 'dimmer')])
def test_matter_representation(kind, expected):
    assert bridges.representation(row(channel_kind=kind, matter_enabled=True), 'matter') == (expected, None)


def test_unsupported_matter_semantics_truthful():
    kind, reason = bridges.representation(row(purpose='HVAC', matter_enabled=True), 'matter')
    assert kind is None and 'supported' in reason


@pytest.mark.parametrize('capability,expected', [
    ('light', 'on_off_light'), ('dimmable_light', 'dimmable_light'),
    ('temperature_sensor', 'temperature_sensor'), ('humidity_sensor', 'humidity_sensor'),
    ('illuminance_sensor', 'illuminance_sensor'), ('occupancy_sensor', 'occupancy_sensor'),
    ('motion_sensor', 'occupancy_sensor'), ('contact_sensor', 'contact_sensor'),
])
def test_matter_mapper_is_capability_registry(capability, expected):
    assert bridges.matter_mapper({'capability': capability, 'matter_exposed': True, 'writable': False}) == expected


def test_matter_mapper_keeps_analog_and_generic_relays_internal():
    assert bridges.matter_mapper({'capability': 'analog_value', 'matter_exposed': True, 'writable': False}) is None
    assert bridges.matter_mapper({'capability': 'relay', 'matter_exposed': True, 'writable': True}) is None


def test_canonical_entity_is_stable_across_name_and_area_changes():
    original = row(module_id=7, module_type='LCM', room_id=9, room_name='Kitchen', area_id=3,
                   area_name='Main Floor', logical_name='Kitchen Light',
                   last_state={'state': {'relays': {'A1': True}}},
                   control_session_online=True, logical_enabled=True)
    before = entities.channel_entity(original)
    after = entities.channel_entity({**original, 'display_name': 'Ceiling Light',
                                     'room_name': 'Dining', 'area_name': 'Ground Floor'})
    assert before['entity_id'] == after['entity_id'] == 'channel_1'
    assert before['capability'] == 'light' and before['state'] == {'state': 'ON'}
    assert before['area'] == 'Main Floor' and after['area'] == 'Ground Floor'
    assert before['available'] and before['writable']
    assert before['module_type'] == 'LCM' and before['channel'] == 'A1'


def test_canonical_entity_keeps_unsupported_channel_internally():
    entity = entities.channel_entity(row(purpose='HVAC', channel_kind='relay',
                                         matter_enabled=True, control_session_online=False))
    assert entity['capability'] == 'relay'
    assert not entity['available'] and not entity['state_known']
    assert entity['fault_state'] is None
    assert bridges.representation(row(purpose='HVAC', matter_enabled=True), 'matter')[0] is None


def test_future_channel_capability_remains_visible_without_state_decoder():
    future = row(channel_kind='future_sensor', capability='humidity_sensor',
                 purpose='LIGHTING', matter_enabled=True, control_session_online=True)
    entity = entities.channel_entity(future)
    assert entity['capability'] == 'humidity_sensor'
    assert entity['current_state'] is None and entity['writable'] is False
    assert entity['available'] is True
    assert bridges.representation(future, 'matter')[0] is None


def test_sensor_projection_preserves_source_units_and_is_read_only():
    module = {
        'id': 12, 'device_id': '020000000012', 'module_type': 'SIM',
        'control_session_online': True,
        'last_state': {'state': {'rmc_nodes': {'7': {
            'temperature_f': 71.5, 'humidity_pct': 42, 'lux': 120,
            'presence': True, 'sensor_faults': [], 'stale': False,
        }}, 'hexa_board': {'aio': {'analog_inputs': {
            'a1': {'value': 3.3, 'unit': 'V', 'source': 'ADS1115'},
        }}}}},
    }
    sensors = entities._sensor_entities(module)
    by_capability = {item['capability']: item for item in sensors}
    assert by_capability['temperature_sensor']['state'] == {'value': 71.5, 'unit': '°F'}
    assert by_capability['humidity_sensor']['writable'] is False
    assert by_capability['occupancy_sensor']['state']['value'] is True
    assert by_capability['analog_value']['metadata']['source_detail'] == 'ADS1115'
    assert all(item['matter_exposed'] is False for item in sensors)


def test_sensor_fault_and_stale_state_are_distinct():
    module = {'id': 13, 'device_id': '020000000013', 'module_type': 'SIM',
              'control_session_online': True,
              'last_state': {'state': {'rmc_nodes': {'8': {
                  'temperature_f': 70, 'stale': True, 'sensor_faults': ['temperature'],
              }}}}}
    entity = next(item for item in entities._sensor_entities(module) if item['capability'] == 'temperature_sensor')
    assert entity['availability'] == 'faulted'
    assert entity['fault_state'] == ['temperature']
    module['last_state']['state']['rmc_nodes']['8']['sensor_faults'] = []
    entity = next(item for item in entities._sensor_entities(module) if item['capability'] == 'temperature_sensor')
    assert entity['availability'] == 'stale' and entity['available'] is False


def test_entity_filters_do_not_mutate_or_command_projection():
    rows = [entities.channel_entity(row(id=1, module_id=2, device_id='020000000002', module_type='RCM',
                                        control_session_online=True, logical_enabled=True)),
            entities.channel_entity(row(id=2, module_id=3, device_id='020000000003', module_type='LCM',
                                        channel_id='10-1', channel_kind='lv_dimmer', purpose='LIGHTING',
                                        control_session_online=True, logical_enabled=True))]
    assert [item['entity_id'] for item in entities.filter_entities(rows, module='LCM')] == ['channel_2']
    assert entities.filter_entities(rows, capability='dimmable_light')[0]['entity_id'] == 'channel_2'
    assert entities.filter_entities(rows, availability='unknown') == rows
    assert all(item['writable'] for item in rows)


@pytest.mark.parametrize('roles', [['G', 'Y1'], ['G', 'Y1', 'Y2'], ['G', 'W1'], ['G', 'W1', 'W2']])
async def test_rcm_same_family_allowed(tmp_path, roles):
    agent = rcm.RCMAgent({'runtime_root': str(tmp_path), 'identity_path': str(tmp_path / 'identity.json')})
    agent.channel_metadata = {f'A{i}': {'purpose': 'HVAC', 'hvac_control': role} for i, role in enumerate(roles, 1)}
    for i in range(1, len(roles) + 1):
        assert (await agent.apply_command({'op': 'set_relay', 'channel': f'A{i}', 'value': True}))['ok']


@pytest.mark.parametrize('heating', ['W1', 'W2', 'AUX', 'E'])
@pytest.mark.parametrize('operation', ['set_relay', 'simulate_relay'])
async def test_rcm_conflicting_family_rejected(tmp_path, heating, operation):
    agent = rcm.RCMAgent({'runtime_root': str(tmp_path), 'identity_path': str(tmp_path / 'identity.json')})
    agent.channel_metadata = {'A1': {'purpose': 'HVAC', 'hvac_control': heating}, 'A2': {'purpose': 'HVAC', 'hvac_control': 'Y1'}}
    await agent.apply_command({'op': operation, 'channel': 'A1', 'value': True})
    result = await agent.apply_command({'op': operation, 'channel': 'A2', 'value': True})
    assert not result['ok'] and result['error'] == 'hvac_heating_cooling_interlock'
    assert agent.relays.get('A2') is False


@pytest.mark.parametrize('old,new,temp', [('HEAT','COOL',75), ('COOL','HEAT',60)])
async def test_mode_transition_drops_old_before_new(monkeypatch, old, new, temp):
    events = []
    async def output(name, value):
        events.append((name,value))
    h = hvac.HVACController(output, AsyncMock())
    h.DAMPER_LEAD_S = h.FAN_LEAD_S = 0
    h.COOL_RESTART_LOCKOUT_S = h.HEAT_RESTART_LOCKOUT_S = 0
    h.state.mode = hvac.Mode(new)
    setattr(h.state, old.lower(), True)
    h.state.fan = True
    h.rooms['Room'] = hvac.RoomReading('Room',temp,True,False)
    await h.evaluate()
    assert events.index((old,False)) < events.index((new,True))
    assert not (h.state.heat and h.state.cool)


async def test_transition_honors_destination_lockout(monkeypatch):
    events = []
    async def output(name,value): events.append((name,value))
    h = hvac.HVACController(output, AsyncMock())
    h.state.mode = hvac.Mode.COOL
    h.state.heat = h.state.fan = True
    h.state.last_cool_off = 100
    h.rooms['Room'] = hvac.RoomReading('Room',75,True,False)
    monkeypatch.setattr(hvac.time,'monotonic',lambda: 150)
    await h.evaluate()
    assert ('HEAT',False) in events and ('COOL',True) not in events
    assert h.state.fan and h.state.postrun_until == 210


async def test_hcm_semantic_mapping_stops_opposite_first(monkeypatch):
    records = [row(hvac_control=role, purpose='HVAC', channel_id=ch, logical_name=name, logical_enabled=True)
               for role,ch,name in [('G','D8','Fan'),('W1','C3','Heat'),('Y1','B7','Cool'),('Y2','B8','Cool Stage 2')]]
    monkeypatch.setattr(registry,'channels',AsyncMock(return_value=records))
    command = AsyncMock(return_value={'ok': True})
    await registry.thermostat_output('HEAT',True,command)
    assert [(call.args[0],call.args[1]['value']) for call in command.call_args_list] == [('Cool',False),('Cool Stage 2',False),('Heat',True)]


async def test_semantic_on_aborts_when_opposite_off_fails(monkeypatch):
    records = [row(hvac_control=role, purpose='HVAC', logical_name=role, logical_enabled=True) for role in ['W1','Y1']]
    monkeypatch.setattr(registry,'channels',AsyncMock(return_value=records))
    command=AsyncMock(return_value={'ok':False})
    with pytest.raises(RuntimeError): await registry.thermostat_output('HEAT',True,command)
    assert command.await_count == 1


async def test_metadata_safety_off_ignores_normal_commissioning_gate(tmp_path):
    agent = rcm.RCMAgent({'runtime_root':str(tmp_path),'identity_path':str(tmp_path/'id.json')})
    agent.channel_metadata={'A1':{'purpose':'HVAC','hvac_control':'Y1'}}
    agent.relays.set('A1',True)
    result=await agent.apply_command({'op':'metadata_hvac_off'})
    assert result['ok'] and agent.relays.get('A1') is False


async def test_external_command_rechecks_permission(monkeypatch):
    monkeypatch.setattr(registry,'channels',AsyncMock(return_value=[row()]))
    with pytest.raises(PermissionError):
        await bridges.external_command('mqtt',1,True)


async def test_metadata_sync_persists_interlock_without_actuation(tmp_path):
    config={'runtime_root':str(tmp_path),'identity_path':str(tmp_path/'id.json')}
    agent=rcm.RCMAgent(config)
    rows=[{'channel_id':ch,'metadata':contract.ChannelMetadata().model_dump(mode='json')} for ch in agent.relays.values]
    for entry,role in zip(rows,['G','Y1','W1']):
        entry['metadata'].update(purpose='HVAC',hvac_control=role)
    result=await agent.apply_config({'channel_metadata':rows})
    assert result['metadata_contract']==1 and not result['physical_outputs_commanded']
    assert not any(agent.relays.snapshot().values())
    restored=rcm.RCMAgent(config)
    assert restored.channel_metadata['A3']['hvac_control']=='W1'
    await restored.apply_command({'op':'set_relay','channel':'A2','value':True})
    assert not (await restored.apply_command({'op':'set_relay','channel':'A3','value':True}))['ok']


async def test_mqtt_discovery_removal_and_metadata_changes(monkeypatch):
    class Conn:
        def __init__(self): self.topics=set()
        async def fetch(self,*args): return [{'topic':t} for t in self.topics]
        async def execute(self,sql,topic):
            if sql.startswith('INSERT'): self.topics.add(topic)
            else: self.topics.discard(topic)
    from contextlib import asynccontextmanager
    conn=Conn()
    @asynccontextmanager
    async def acquire(): yield conn
    monkeypatch.setattr(bridges.db,'acquire',acquire)
    bridge=bridges.RegistryBridge();bridge.client=AsyncMock()
    bridge.rows=[row(mqtt_enabled=True)]
    await bridge.sync_mqtt()
    topic=next(iter(conn.topics))
    bridge.rows=[row(mqtt_enabled=True,display_name='Renamed',room_name='Kitchen')]
    await bridge.sync_mqtt()
    assert conn.topics=={topic}
    import json
    body=json.loads(bridge.client.publish.call_args.args[1])
    assert body['name']=='Renamed' and body['device']['suggested_area']=='Kitchen'
    bridge.rows=[row(mqtt_enabled=False)]
    await bridge.sync_mqtt()
    assert not conn.topics
    assert bridge.client.publish.call_args.args == (topic,'')


def test_reported_state_never_invents_feedback():
    assert bridges.reported_state(row()) is None
    assert bridges.reported_state(row(last_state={'state':{'relays':{'A1':False}}})) == {'state':'OFF'}


async def test_matter_child_exit_restarts_on_registry_reconciliation(monkeypatch):
    bridge = bridges.RegistryBridge()
    bridge.settings = {'mqtt': {'enabled': False}, 'matter': {'enabled': True}}
    bridge.matter = SimpleNamespace(returncode=1)
    bridge.matter_reader = asyncio.create_task(asyncio.sleep(0))
    monkeypatch.setattr(bridge, 'load_settings', AsyncMock(return_value=bridge.settings))
    monkeypatch.setenv('HCM_MATTER_STORAGE', '/tmp/hcm-matter-test')
    monkeypatch.setenv('HCM_MATTER_PASSCODE', '12345678')

    async def start():
        bridge.matter = SimpleNamespace(returncode=None)
    starter = AsyncMock(side_effect=start)
    monkeypatch.setattr(bridge, 'start_matter', starter)

    await bridge.configure()
    starter.assert_awaited_once()
    assert bridge.matter_reader is None
    await bridge.configure()
    starter.assert_awaited_once()


async def test_matter_failures_back_off_and_disabled_setting_does_not_restart(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(bridges.time, 'monotonic', lambda: clock[0])
    monkeypatch.setenv('HCM_MATTER_STORAGE', '/tmp/hcm-matter-test')
    monkeypatch.setenv('HCM_MATTER_PASSCODE', '12345678')
    bridge = bridges.RegistryBridge()
    enabled = {'mqtt': {'enabled': False}, 'matter': {'enabled': True}}
    bridge.settings = enabled
    bridge._matter_failure('adapter exited')
    assert bridge.matter_next_retry == 105
    bridge._matter_failure('adapter exited')
    assert bridge.matter_next_retry == 110
    bridge._matter_failure('adapter exited')
    assert bridge.matter_next_retry == 120 and bridge.matter_state.startswith('failed repeatedly')
    monkeypatch.setattr(bridge, 'load_settings', AsyncMock(return_value=enabled))
    starter = AsyncMock(side_effect=lambda: setattr(bridge, 'matter', SimpleNamespace(returncode=None)))
    monkeypatch.setattr(bridge, 'start_matter', starter)
    await bridge.configure()
    starter.assert_not_awaited()
    clock[0] = 120
    await bridge.configure()
    starter.assert_awaited_once()

    bridge.matter = SimpleNamespace(returncode=None, terminate=Mock(), wait=AsyncMock())
    bridge.matter_reader = asyncio.create_task(asyncio.sleep(0))
    monkeypatch.setattr(bridge, 'load_settings', AsyncMock(return_value={'mqtt': enabled['mqtt'], 'matter': {'enabled': False}}))
    await bridge.configure()
    assert bridge.matter_state == 'disabled'
    await bridge.configure()
    starter.assert_awaited_once()


async def test_hcm_cross_module_interlock_rejects_active_cooling(monkeypatch):
    devices=import_module('01_HCM.devices')
    records=[row(id=901,device_id='020000000001',purpose='HVAC',hvac_control='Y1',last_state={'relays':{'A1':True}})]
    monkeypatch.setattr(registry,'channels',AsyncMock(return_value=records))
    dispatch=AsyncMock()
    monkeypatch.setattr(devices,'_dispatch_resolved',dispatch)
    with pytest.raises(PermissionError,match='interlock'):
        await devices._dispatch_with_arbitration({'metadata':{'semantic_hvac':True,'hvac_control':'W1','metadata_channel_id':902}}, {'value':True},'user')
    dispatch.assert_not_called()
