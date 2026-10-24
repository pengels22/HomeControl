from importlib import import_module

import pytest


sim = import_module('05_PNL.simulation')


LAYOUT = {'version': 1, 'theme': 'dark', 'pages': [{'id': 'main', 'title': 'Main', 'cards': [
    {'id': 'light', 'type': 'button', 'entity': 'light.main', 'bounds': {'x': 0, 'y': 0, 'w': 200, 'h': 100}},
    {'id': 'dimmer', 'type': 'slider', 'entity': 'light.main', 'bounds': {'x': 210, 'y': 0, 'w': 200, 'h': 100}},
    {'id': 'temp', 'type': 'entity', 'entity': 'local.temp', 'bounds': {'x': 420, 'y': 0, 'w': 200, 'h': 100}},
    {'id': 'all', 'type': 'entities', 'entities': 'area.current', 'bounds': {'x': 0, 'y': 110, 'w': 300, 'h': 160}},
    {'id': 'hvac', 'type': 'thermostat', 'entity': 'climate.home', 'bounds': {'x': 310, 'y': 110, 'w': 300, 'h': 160}},
]}]}


def make_system():
    hcm = sim.SimulatedHCM()
    hcm.publish_dashboard('shared', LAYOUT)
    for area in hcm.areas:
        hcm.assign_dashboard(area, 'shared')
    panels = [
        hcm.register_panel('02:00:00:00:00:10', 'PNL-001', 'pnl-living', 'Living Room', 'living-token'),
        hcm.register_panel('02:00:00:00:00:20', 'PNL-002', 'pnl-kitchen', 'Kitchen', 'kitchen-token'),
        hcm.register_panel('02:00:00:00:00:30', 'PNL-003', 'pnl-bedroom', 'Bedroom', 'bedroom-token'),
    ]
    return hcm, panels


def test_three_panels_register_assign_report_and_render_independent_locals():
    hcm, panels = make_system()
    for index, panel in enumerate(panels):
        panel.connect(hcm)
        panel.set_sensor('temp', 20 + index)
        panel.set_sensor('lux', 100 + index)
        panel.set_sensor('humidity', 40 + index)
        panel.set_sensor('occupancy', bool(index % 2))
        panel.send_telemetry(5)
        panel.send_heartbeat(5)
        assert panel.dashboard['pages'][0]['cards'][2]['entity'] == 'local.temp'
    assert [hcm.telemetry[p.device_id]['local']['temp'] for p in panels] == [20, 21, 22]
    assert all(hcm.panel_status(panel, 10) == {'telemetry_fresh': True, 'heartbeat_connected': True} for panel in panels)


def test_occupancy_is_immediate_and_heartbeat_is_independent_from_telemetry():
    hcm, (panel, *_rest) = make_system()
    panel.connect(hcm)
    panel.send_heartbeat(0)
    panel.occupancy_change(True, 1)
    assert hcm.occupancy_events[-1]['occupied'] is True
    assert hcm.panel_status(panel, 16) == {'telemetry_fresh': False, 'heartbeat_connected': False}
    panel.send_heartbeat(16)
    assert hcm.panel_status(panel, 16)['heartbeat_connected'] is True
    assert hcm.panel_status(panel, 16)['telemetry_fresh'] is False


def test_commands_are_hcm_authoritative_and_duplicate_safe():
    hcm, (panel, *_rest) = make_system()
    panel.connect(hcm)
    accepted = hcm.command(panel, 'cmd-1', 'button', 'light.main', True)
    assert accepted['status'] == 'accepted' and accepted['physical_success'] is False
    assert hcm.command(panel, 'cmd-1', 'button', 'light.main', True)['status'] == 'duplicate'
    assert hcm.command(panel, 'cmd-local', 'entity', 'local.temp', 22)['status'] == 'rejected'
    hcm.online = False
    assert hcm.command(panel, 'cmd-offline', 'slider', 'light.main', 50)['status'] == 'unavailable'


def test_dashboard_update_and_sonic_svr1_session_survive_reconnect_boundaries():
    hcm, panels = make_system()
    panel = panels[0]
    panel.connect(hcm)
    old_sha = panel.last_display['layout_sha256']
    hcm.publish_dashboard('shared', {**LAYOUT, 'theme': 'updated'})
    hcm.online = False
    assert panel.dashboard['theme'] == 'dark'  # last-known-good local display
    hcm.online = True
    panel.connect(hcm)
    assert panel.last_display['layout_sha256'] != old_sha
    hcm.set_microphones(False, 10)
    session = panel.start_voice(10)
    result = hcm.transcribe(session, 'turn on the light')
    assert result['intent_dispatched'] is True
    hcm.set_microphones(True, 11)
    assert panel.microphone_muted is True
    with pytest.raises(sim.SimulationError, match='muted'):
        panel.start_voice(12)


def test_unauthorized_identity_and_invalid_revision_are_rejected():
    hcm, panels = make_system()
    rogue = sim.SimulatedPanel('02:00:00:00:00:40', 'PNL-999', 'rogue', 'Living Room', 'bad')
    with pytest.raises(sim.SimulationError, match='unauthorized'):
        rogue.connect(hcm)
    with pytest.raises(sim.dashboard.DashboardError):
        hcm.publish_dashboard('invalid', {'version': 1, 'pages': []})
