from __future__ import annotations
import asyncio, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
channel_contract = import_module('08_servises.common.channel_metadata')
common_agent = import_module('08_servises.common.agent')
common_cfg = import_module('08_servises.common.config')
common_hw = import_module('08_servises.common.hardware')
common_pinmap = import_module('08_servises.common.pinmap')
common_io = import_module('08_servises.common.io')
common_global_config = import_module('08_servises.common.global_config')
common_safety = import_module('08_servises.common.safety_arbiter')
common_infra = import_module('08_servises.common.module_infra')
common_profiles = import_module('08_servises.common.hardware_profiles')
common_commissioning = import_module('08_servises.common.commissioning')
common_drivers = import_module('08_servises.common.physical_drivers')
common_factory = import_module('08_servises.common.hardware_factory')
state_confidence = import_module('08_servises.common.state_confidence')

class RCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('RCM', config)
        self.local_input_poll_interval_s = 0.01
        self.global_config = common_global_config.load_global_config('RCM')
        self.hardware_profile = config.get('hardware_profile', {})
        if not isinstance(self.hardware_profile, dict) or not self.hardware_profile:
            root = Path(__file__).resolve().parents[1]
            self.hardware_profile = common_profiles.load_profile(
                root / '07_config/04_RCM/hardware_pins.yaml', 'RCM'
            ).data
        relay_count = int(config.get('relay_count', self.global_config.RCM_Relay_Count))
        names = common_infra.RCM_RELAY_CHANNELS[:relay_count]
        profile_map = self.hardware_profile.get('outputs', {}).get('relays', {}).get('mappings', {})
        self.pinout = {
            ch: common_pinmap.PinMapEntry(
                ch,
                f"{profile_map[ch]['device']} index {profile_map[ch]['index']}",
                'Relay',
                'UNVERIFIED',
            )
            for ch in names
            if ch in profile_map
        }
        common_pinmap.require_channels(self.pinout, names)
        self.io_mode = common_io.io_mode(config)
        # Real I/O mode never accepts a simulation command, even while the
        # manifest keeps physical outputs disabled.
        self.simulation = self.io_mode != 'real'
        hardware_mode = 'mock' if config.get('mock_hardware') else self.io_mode
        self.driver_bundle = common_factory.build_hardware_bundle('RCM', {**config, 'hardware_mode': hardware_mode}, self.hardware_profile)
        if self.driver_bundle.mode in {'simulated', 'disabled'}:
            self.driver_bundle = None
        if self.driver_bundle:
            self.driver_bundle['rcm_relays'].initialize()
            if self.driver_bundle.get('rcm_inputs'):
                self.driver_bundle['rcm_inputs'].initialize()
        self.relays = common_hw.DigitalBank(names)
        self._pending_override_operations: list[tuple[int, bool]] = []
        self.bank_controller = common_infra.RCMBankController(self._queue_override)
        self.relay_hardware_map = {ch: common_infra.RCM_RELAY_MAP[ch] for ch in names}
        if profile_map:
            self.relay_hardware_map = {
                ch: (str(item['device']), int(item['index']))
                for ch, item in profile_map.items() if ch in names
            }
        default_on = bool(config.get('default_relay_on', self.global_config.RCM_Default_Relay_On))
        if default_on:
            for ch in names:
                self.relays.set(ch, True)
        self.fail_actions = config.get('fail_actions', {})
        safety_cfg = config.get('safety', {})
        self.safety = common_safety.SafetyArbiter(
            emergency_lighting_channels=set(safety_cfg.get('emergency_lighting_channels', [])),
            hvac_shutdown_channels=set(safety_cfg.get('hvac_shutdown_channels', [])),
        )

        import json
        try:
            cached = json.loads((self.runtime_root / '.state' / f'channel-metadata-{self.module_type}.json').read_text())
            result = self.accept_channel_metadata([{'channel_id': ch, 'metadata': value} for ch, value in cached.items()])
            if not result['ok']:
                raise ValueError(result['error'])
        except FileNotFoundError:
            pass  # Legacy configuration remains authoritative until first sync.

    def _hvac_interlock(self, channel, value):
        roles = {ch: metadata['hvac_control'] for ch, metadata in getattr(self, 'channel_metadata', {}).items() if metadata['purpose'] == 'HVAC'}
        candidate = {**self.relays.snapshot(), channel: value}
        return channel_contract.hvac_conflict(roles, candidate)

    def _safety_requires_output_shutdown(self, conditions):
        return any(bool((conditions or {}).get(name)) for name in (
            'maintenance_lockout',
            'fire_input_fault',
            'communication_loss',
            'arbiter_fault',
        ))

    def _deenergize_all_relays_for_safety(self):
        decisions = []
        failures = []
        for ch in list(self.relays.values):
            decision = self.safety.decide(common_safety.OutputRequest(
                self.identity.get('device_id'),
                ch,
                {'op': 'set_relay', 'channel': ch, 'value': False, 'source': 'safety_state'},
                'safety_state',
            ))
            self.relays.set(ch, bool(decision.final_command.get('value', False)))
            if self.io_mode == 'real' and self.driver_bundle and self.driver_bundle.get('rcm_relays'):
                try:
                    self.driver_bundle['rcm_relays'].set_channel(
                        common_infra.RCM_RELAY_CHANNELS.index(ch), False
                    )
                except Exception as exc:
                    logging.getLogger(__name__).exception('failed to deenergize %s', ch)
                    failures.append({'channel': ch, 'error': str(exc)})
            decisions.append(decision.as_dict())
        return {'decisions': decisions, 'failures': failures, 'safe_state_attempted': self.io_mode == 'real'}

    async def collect_state(self):
        return {
            'relays': self.relays.snapshot(),
            'bank_selector': self.bank_controller.status(int(time.monotonic() * 1000) & 0xFFFFFFFF),
            'relay_hardware_map': {
                channel: {'component': component, 'index': index}
                for channel, (component, index) in self.relay_hardware_map.items()
            },
            'state_confidence': 'commanded_only_no_contact_feedback',
            'state_confidence_label': state_confidence.COMMANDED if self.io_mode == 'real' else state_confidence.SIMULATED,
            'io_mode': self.io_mode,
            'pinout': {
                channel: {
                    'hardware_address': entry.hardware_address,
                    'function': entry.function,
                    'field_voltage': entry.field_voltage,
                }
                for channel, entry in self.pinout.items()
                if channel in self.relays.values
            },
            'safety': self.safety.snapshot(),
            'hardware_profile': {
                'verification': self.hardware_profile.get('verification', {}),
                'physical_output_enabled': self.hardware_profile.get('physical_output_enabled', False),
                'commissioning': common_commissioning.commissioning_status(
                    self.hardware_profile, list(self.relays.values)
                ),
            },
            'hardware_driver': self.driver_bundle['rcm_relays'].diagnostics() if self.driver_bundle else {'mode': 'not_instantiated'},
        }

    def _queue_override(self, channel_index: int, value: bool) -> None:
        self._pending_override_operations.append((int(channel_index), bool(value)))

    async def poll_local_inputs(self) -> None:
        if not self.driver_bundle or not self.driver_bundle.get('rcm_inputs'):
            return
        try:
            ports = self.driver_bundle['rcm_inputs'].read_ports()
            status = self.bank_controller.update_from_raw(
                ports['mcp2_gpa'], ports['mcp1_gpa'], ports['mcp1_gpb'],
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
            )
            pending = list(self._pending_override_operations)
            self._pending_override_operations.clear()
            for channel_index, value in pending:
                channel = common_infra.RCM_RELAY_CHANNELS[channel_index]
                await self.apply_command({
                    'op': 'set_relay',
                    'channel': channel,
                    'value': value,
                    'source': 'local_override',
                    'physical_write_requested': self.io_mode == 'real',
                })
            self.state['bank_selector'] = status
        except Exception as exc:
            logging.getLogger(__name__).exception('RCM front-panel input poll failed')
            self.faults['front_panel_inputs'] = {'error': str(exc)}

    async def apply_command(self, payload):
        if payload.get('op') == 'metadata_hvac_off':
            failures = []
            metadata = getattr(self, 'channel_metadata', {})
            targets = {ch for ch, value in metadata.items() if value['purpose'] == 'HVAC'} | self.safety.hvac_shutdown_channels
            for ch in sorted(targets):
                try:
                    if ch not in self.relays.values:
                        raise ValueError('unknown HVAC relay')
                    if self.io_mode == 'real':
                        if not self.driver_bundle or not self.driver_bundle.get('rcm_relays'):
                            raise RuntimeError('physical driver unavailable')
                        self.driver_bundle['rcm_relays'].set_channel(common_infra.RCM_RELAY_CHANNELS.index(ch), False)
                    self.relays.set(ch, False)
                except Exception as exc:
                    failures.append({'channel': ch, 'error': str(exc)})
            return {'ok': not failures, 'failures': failures, 'attempted': sorted(targets)}

        if payload.get('op') == 'simulate_relay':
            if not self.simulation:
                return {
                    'ok': False,
                    'error': 'simulation command rejected by physical-output safety gate',
                    'simulation': False,
                    'physical_outputs_commanded': False,
                }
            ch = payload['channel'].upper()
            if bool(payload['value']) and self._hvac_interlock(ch, True):
                return {'ok': False, 'error': 'hvac_heating_cooling_interlock', 'physical_outputs_commanded': False}
            self.relays.set(ch, bool(payload['value']))
            return {
                'ok': True,
                'channel': ch,
                'value': self.relays.get(ch),
                'simulation': True,
                'physical_outputs_commanded': False,
                'state_confidence': 'simulated_commanded_only',
                'state_confidence_label': state_confidence.SIMULATED,
            }
        if payload.get('op') == 'safety_state':
            conditions = payload.get('conditions', {})
            self.safety.update_conditions(conditions)
            result = self._deenergize_all_relays_for_safety() if self._safety_requires_output_shutdown(conditions) else {'decisions': [], 'failures': [], 'safe_state_attempted': False}
            return {'ok': not result['failures'], 'safety': self.safety.snapshot(), 'arbitration': result['decisions'], 'safe_state_attempted': result['safe_state_attempted'], 'failures': result['failures']}
        if payload.get('op') == 'set_relay':
            ch = payload['channel'].upper()
            physical_requested = bool(payload.get('physical_write_requested'))
            if physical_requested and self.io_mode != 'real':
                return {'ok': False, 'error': 'io_mode_not_real', 'channel': ch, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            decision = self.safety.decide(common_safety.OutputRequest(
                self.identity.get('device_id'),
                ch,
                payload,
                payload.get('source', 'module_api'),
            ))
            if physical_requested and bool(decision.final_command.get('value', False)) and not common_commissioning.physical_write_allowed(self.hardware_profile, ch):
                return {'ok': False, 'error': common_commissioning.physical_write_denial_reason(self.hardware_profile, ch), 'channel': ch, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            if bool(decision.final_command.get('value', False)) and self._hvac_interlock(ch, True):
                return {'ok': False, 'error': 'hvac_heating_cooling_interlock', 'physical_outputs_commanded': False}
            physical_commanded = False
            if physical_requested:
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': ch, 'physical_outputs_commanded': False}
                self.driver_bundle['rcm_relays'].set_channel(
                    common_infra.RCM_RELAY_CHANNELS.index(ch),
                    bool(decision.final_command.get('value', False)),
                )
                physical_commanded = True
            self.relays.set(ch, bool(decision.final_command.get('value', False)))
            entry = self.pinout.get(ch)
            hardware_address = (
                f"{self.relay_hardware_map[ch][0]} index {self.relay_hardware_map[ch][1]}"
                if ch in self.relay_hardware_map and self.hardware_profile.get('outputs')
                else entry.hardware_address
            )
            return {
                'ok': True,
                'channel': ch,
                'hardware_address': hardware_address,
                'value': self.relays.get(ch),
                'requested_value': bool(payload['value']),
                'state_confidence': 'commanded_only_no_contact_feedback',
                'arbitration': decision.as_dict(),
                'physical_output_commanded': physical_commanded,
                'state_confidence_label': state_confidence.OUTPUT_LATCH_READBACK if physical_commanded else (state_confidence.COMMANDED if self.io_mode == 'real' else state_confidence.SIMULATED),
                'physical_write_allowed': common_commissioning.physical_write_allowed(self.hardware_profile, ch),
            }
        if payload.get('op') == 'all_off':
            decisions = []
            failures = []
            for ch in list(self.relays.values):
                decision = self.safety.decide(common_safety.OutputRequest(
                    self.identity.get('device_id'),
                    ch,
                    {'op': 'set_relay', 'channel': ch, 'value': False},
                    payload.get('source', 'module_api'),
                ))
                self.relays.set(ch, bool(decision.final_command.get('value', False)))
                if self.io_mode == 'real' and self.driver_bundle and self.driver_bundle.get('rcm_relays'):
                    try:
                        self.driver_bundle['rcm_relays'].set_channel(common_infra.RCM_RELAY_CHANNELS.index(ch), False)
                    except Exception as exc:
                        logging.getLogger(__name__).exception('failed to all-off %s', ch)
                        failures.append({'channel': ch, 'error': str(exc)})
                decisions.append(decision.as_dict())
            return {'ok': not failures, 'arbitration': decisions, 'safe_state_attempted': self.io_mode == 'real', 'failures': failures}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    root = Path(__file__).resolve().parents[1]
    cfg = common_cfg.load_yaml(root / '07_config/04_RCM/rcm.yaml')
    cfg['hardware_profile'] = common_profiles.load_profile(
        root / '07_config/04_RCM/hardware_pins.yaml', 'RCM'
    ).data
    await RCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
