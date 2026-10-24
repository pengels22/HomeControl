"""Deterministic software-only PNL/HCM integration simulator.

This models the contracts at the system boundary without pretending to validate
ESP32, W5500, microphone, or touchscreen hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from homecontrol_identity import normalize_device_id

dashboard = import_module('05_PNL.dashboard')
heartbeat = import_module('00_Heartbeat.hcm_heartbeat')


class SimulationError(ValueError):
    pass


@dataclass
class SimulatedPanel:
    device_id: str
    friendly_id: str
    hostname: str
    area: str
    version: str = 'sim-1.0'
    token: str = ''
    connected: bool = False
    hcm: 'SimulatedHCM | None' = field(default=None, repr=False)
    local: dict[str, Any] = field(default_factory=lambda: {'lux': None, 'occupancy': None, 'temp': None, 'humidity': None})
    validity: dict[str, bool] = field(default_factory=lambda: {'lux': False, 'occupancy': False, 'temp': False, 'humidity': False})
    telemetry_sequence: int = 0
    heartbeat_sequence: int = 0
    dashboard: dict[str, Any] | None = None
    microphone_muted: bool = True
    voice_session: str | None = None
    last_display: dict[str, Any] = field(default_factory=dict)

    def connect(self, hcm: 'SimulatedHCM') -> dict[str, Any]:
        self.hcm = hcm
        result = hcm.authenticate_panel(self)
        self.connected = True
        self.receive_dashboard(result['dashboard'])
        self.apply_sonic_policy(result['sonic_policy'])
        return result

    def disconnect(self) -> None:
        self.connected = False
        self.microphone_muted = True
        self.voice_session = None

    def receive_dashboard(self, layout: dict[str, Any]) -> None:
        compiled = dashboard.compile_dashboard(layout)
        self.dashboard = compiled['layout']
        self.last_display = {'layout_sha256': compiled['sha256'], 'preview_only': True}

    def set_sensor(self, key: str, value: Any, valid: bool = True) -> None:
        if key not in self.local:
            raise SimulationError(f'unknown local sensor {key}')
        self.local[key] = value if valid else None
        self.validity[key] = bool(valid)

    def send_telemetry(self, now: float) -> dict[str, Any]:
        if not self.connected or not self.hcm:
            raise SimulationError('panel is not connected')
        self.telemetry_sequence += 1
        payload = self.hcm.ingest_telemetry(self, now)
        return payload

    def send_heartbeat(self, now: float) -> dict[str, Any]:
        if not self.connected or not self.hcm:
            raise SimulationError('panel is not connected')
        self.heartbeat_sequence += 1
        return self.hcm.ingest_heartbeat(self, now)

    def occupancy_change(self, occupied: bool, now: float) -> dict[str, Any]:
        self.set_sensor('occupancy', occupied)
        if not self.connected or not self.hcm:
            raise SimulationError('panel is not connected')
        return self.hcm.ingest_occupancy(self, occupied, now)

    def apply_sonic_policy(self, policy: dict[str, Any]) -> bool:
        accepted = (policy['epoch'] >= getattr(self, '_policy_epoch', 0)
                    and (policy['expires_at'] is None or policy['expires_at'] >= policy.get('now', 0)))
        self._policy_epoch = policy['epoch'] if accepted else getattr(self, '_policy_epoch', 0)
        self.microphone_muted = True if not accepted else bool(policy['globally_muted'])
        if self.microphone_muted:
            self.voice_session = None
        return accepted

    def start_voice(self, now: float) -> str:
        if self.microphone_muted or not self.connected or not self.hcm:
            raise SimulationError('microphone is muted')
        self.voice_session = self.hcm.start_voice_session(self, now)
        return self.voice_session


class SimulatedHCM:
    """In-memory HCM authority used by deterministic integration tests."""

    def __init__(self):
        self.areas = {'Living Room', 'Kitchen', 'Bedroom'}
        self.panels: dict[str, SimulatedPanel] = {}
        self.dashboards: dict[str, dict[str, Any]] = {}
        self.area_dashboards: dict[str, str] = {}
        self.entities = {'Living Room': {'light.main': False}, 'Kitchen': {'light.main': False}, 'Bedroom': {'light.main': False}}
        self.entity_state: dict[str, Any] = {}
        self.telemetry: dict[str, dict[str, Any]] = {}
        self.occupancy_events: list[dict[str, Any]] = []
        self.heartbeat: dict[str, float] = {}
        self.online = True
        self.command_ids: set[str] = set()
        self.command_log: list[dict[str, Any]] = []
        self._revision = 0
        self.sonic = {'epoch': 1, 'globally_muted': True, 'expires_at': None, 'now': 0}
        self.voice_sessions: dict[str, dict[str, Any]] = {}

    def register_panel(self, mac: str, friendly_id: str, hostname: str, area: str, token: str, version: str = 'sim-1.0') -> SimulatedPanel:
        device_id = normalize_device_id(mac)
        if area not in self.areas or device_id in self.panels or any(p.friendly_id == friendly_id for p in self.panels.values()):
            raise SimulationError('panel identity or area is already registered')
        panel = SimulatedPanel(device_id, friendly_id, hostname, area, version, token)
        self.panels[device_id] = panel
        return panel

    def assign_area(self, panel: SimulatedPanel, area: str) -> None:
        if panel.device_id not in self.panels or area not in self.areas:
            raise SimulationError('unknown panel or area')
        panel.area = area

    def publish_dashboard(self, name: str, layout: dict[str, Any]) -> int:
        compiled = dashboard.compile_dashboard(layout)
        self._revision += 1
        self.dashboards[name] = {'revision': self._revision, 'layout': compiled['layout'], 'sha256': compiled['sha256']}
        return self._revision

    def assign_dashboard(self, area: str, name: str) -> None:
        if area not in self.areas or name not in self.dashboards:
            raise SimulationError('unknown dashboard assignment')
        self.area_dashboards[area] = name

    def authenticate_panel(self, panel: SimulatedPanel) -> dict[str, Any]:
        if self.panels.get(panel.device_id) is not panel or not panel.token:
            raise SimulationError('unauthorized panel')
        name = self.area_dashboards.get(panel.area)
        if not name:
            raise SimulationError('no dashboard assigned to panel area')
        return {'panel': panel.friendly_id, 'area': panel.area, 'dashboard': self.dashboards[name]['layout'], 'dashboard_revision': self.dashboards[name]['revision'], 'sonic_policy': self.sonic}

    def ingest_telemetry(self, panel: SimulatedPanel, now: float) -> dict[str, Any]:
        if not self.online or self.panels.get(panel.device_id) is not panel:
            raise SimulationError('HCM unavailable or panel unauthorized')
        previous = self.telemetry.get(panel.device_id)
        if previous and panel.telemetry_sequence <= previous['sequence']:
            raise SimulationError('telemetry replay')
        sample = {'device_id': panel.device_id, 'sequence': panel.telemetry_sequence, 'received_at': now, 'local': dict(panel.local), 'validity': dict(panel.validity)}
        self.telemetry[panel.device_id] = sample
        return sample

    def ingest_occupancy(self, panel: SimulatedPanel, occupied: bool, now: float) -> dict[str, Any]:
        prior = self.occupancy_events[-1] if self.occupancy_events and self.occupancy_events[-1]['device_id'] == panel.device_id else None
        if prior and prior['occupied'] == occupied:
            return prior
        event = {'device_id': panel.device_id, 'sequence': panel.telemetry_sequence + 1, 'occupied': occupied, 'at': now}
        self.occupancy_events.append(event)
        return event

    def ingest_heartbeat(self, panel: SimulatedPanel, now: float) -> dict[str, Any]:
        self.heartbeat[panel.device_id] = now
        return {'protocol': 'hcm-heartbeat-v3', 'version': heartbeat.VERSION, 'device_id': panel.device_id, 'sequence': panel.heartbeat_sequence, 'ack': True}

    def panel_status(self, panel: SimulatedPanel, now: float) -> dict[str, bool]:
        telemetry = self.telemetry.get(panel.device_id)
        return {'telemetry_fresh': bool(telemetry and now - telemetry['received_at'] <= 15), 'heartbeat_connected': now - self.heartbeat.get(panel.device_id, -10**9) <= 15}

    def command(self, panel: SimulatedPanel, command_id: str, card_type: str, entity: str, value: Any) -> dict[str, Any]:
        if not self.online or self.panels.get(panel.device_id) is not panel or not panel.connected:
            return {'command_id': command_id, 'status': 'unavailable'}
        if command_id in self.command_ids:
            return {'command_id': command_id, 'status': 'duplicate'}
        if card_type not in {'button', 'slider', 'entity', 'thermostat'}:
            return {'command_id': command_id, 'status': 'rejected', 'reason': 'unsupported card action'}
        if entity.startswith('local.'):
            return {'command_id': command_id, 'status': 'rejected', 'reason': 'local aliases are read-only'}
        self.command_ids.add(command_id)
        logical = f'{panel.area}.{entity}'
        self.entity_state[logical] = value
        ack = {'command_id': command_id, 'status': 'accepted', 'logical_entity': logical, 'value': value, 'physical_success': False}
        self.command_log.append(ack)
        return ack

    def set_microphones(self, muted: bool, now: float, expires_at: float | None = None) -> dict[str, Any]:
        self.sonic = {'epoch': self.sonic['epoch'] + 1, 'globally_muted': muted, 'expires_at': expires_at, 'now': now}
        for panel in self.panels.values():
            panel.apply_sonic_policy(self.sonic)
        return self.sonic

    def start_voice_session(self, panel: SimulatedPanel, now: float) -> str:
        if self.sonic['globally_muted'] or not panel.connected:
            raise SimulationError('voice unavailable')
        session = f'{panel.friendly_id}-{len(self.voice_sessions) + 1}'
        self.voice_sessions[session] = {'panel': panel.device_id, 'area': panel.area, 'started_at': now, 'transport': 'SVR1', 'audio_metadata': {'sample_rate': 16000}}
        return session

    def transcribe(self, session: str, text: str) -> dict[str, Any]:
        record = self.voice_sessions.get(session)
        if not record:
            raise SimulationError('unknown voice session')
        panel = self.panels[record['panel']]
        return {'session': session, 'panel': panel.friendly_id, 'area': record['area'], 'text': text, 'intent_dispatched': True}
