from importlib import import_module
from unittest.mock import AsyncMock
import pytest

contract = import_module('07_servises.common.channel_metadata')
bridges = import_module('01_HCM.bridges')
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


async def test_hcm_cross_module_interlock_rejects_active_cooling(monkeypatch):
    devices=import_module('01_HCM.devices')
    records=[row(id=901,device_id='020000000001',purpose='HVAC',hvac_control='Y1',last_state={'relays':{'A1':True}})]
    monkeypatch.setattr(registry,'channels',AsyncMock(return_value=records))
    dispatch=AsyncMock()
    monkeypatch.setattr(devices,'_dispatch_resolved',dispatch)
    with pytest.raises(PermissionError,match='interlock'):
        await devices._dispatch_with_arbitration({'metadata':{'semantic_hvac':True,'hvac_control':'W1','metadata_channel_id':902}}, {'value':True},'user')
    dispatch.assert_not_called()
