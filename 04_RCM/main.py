from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_cfg = import_module('07_servises.common.config')
common_hw = import_module('07_servises.common.hardware')
common_pinmap = import_module('07_servises.common.pinmap')
common_io = import_module('07_servises.common.io')
common_global_config = import_module('07_servises.common.global_config')
common_safety = import_module('07_servises.common.safety_arbiter')
common_infra = import_module('07_servises.common.module_infra')
common_profiles = import_module('07_servises.common.hardware_profiles')

class RCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('RCM', config)
        self.global_config = common_global_config.load_global_config('RCM')
        self.hardware_profile = config.get('hardware_profile', {})
        if not isinstance(self.hardware_profile, dict) or not self.hardware_profile:
            root = Path(__file__).resolve().parents[1]
            self.hardware_profile = common_profiles.load_profile(
                root / '06_config/04_RCM/hardware_pins.yaml', 'RCM'
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
        self.relays = common_hw.DigitalBank(names)
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

    def _safety_requires_output_shutdown(self, conditions):
        return any(bool((conditions or {}).get(name)) for name in (
            'maintenance_lockout',
            'fire_input_fault',
            'communication_loss',
            'arbiter_fault',
        ))

    def _deenergize_all_relays_for_safety(self):
        decisions = []
        for ch in list(self.relays.values):
            decision = self.safety.decide(common_safety.OutputRequest(
                self.identity.get('device_id'),
                ch,
                {'op': 'set_relay', 'channel': ch, 'value': False, 'source': 'safety_state'},
                'safety_state',
            ))
            self.relays.set(ch, bool(decision.final_command.get('value', False)))
            decisions.append(decision.as_dict())
        return decisions

    async def collect_state(self):
        return {
            'relays': self.relays.snapshot(),
            'relay_hardware_map': {
                channel: {'component': component, 'index': index}
                for channel, (component, index) in self.relay_hardware_map.items()
            },
            'state_confidence': 'commanded_only_no_contact_feedback',
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
            },
        }

    async def apply_command(self, payload):
        if payload.get('op') == 'simulate_relay':
            if self.io_mode == 'real' or payload.get('simulation') is not True or payload.get('physical_outputs_enabled') is not False:
                return {
                    'ok': False,
                    'error': 'simulation command rejected by physical-output safety gate',
                    'simulation': False,
                    'physical_outputs_commanded': False,
                }
            ch = payload['channel'].upper()
            self.relays.set(ch, bool(payload['value']))
            return {
                'ok': True,
                'channel': ch,
                'value': self.relays.get(ch),
                'simulation': True,
                'physical_outputs_commanded': False,
                'state_confidence': 'simulated_commanded_only',
            }
        if payload.get('op') == 'safety_state':
            conditions = payload.get('conditions', {})
            self.safety.update_conditions(conditions)
            decisions = self._deenergize_all_relays_for_safety() if self._safety_requires_output_shutdown(conditions) else []
            return {'ok': True, 'safety': self.safety.snapshot(), 'arbitration': decisions}
        if payload.get('op') == 'set_relay':
            ch = payload['channel'].upper()
            decision = self.safety.decide(common_safety.OutputRequest(
                self.identity.get('device_id'),
                ch,
                payload,
                payload.get('source', 'module_api'),
            ))
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
            }
        if payload.get('op') == 'all_off':
            decisions = []
            for ch in list(self.relays.values):
                decision = self.safety.decide(common_safety.OutputRequest(
                    self.identity.get('device_id'),
                    ch,
                    {'op': 'set_relay', 'channel': ch, 'value': False},
                    payload.get('source', 'module_api'),
                ))
                self.relays.set(ch, bool(decision.final_command.get('value', False)))
                decisions.append(decision.as_dict())
            return {'ok': True, 'arbitration': decisions}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    root = Path(__file__).resolve().parents[1]
    cfg = common_cfg.load_yaml(root / '06_config/04_RCM/rcm.yaml')
    cfg['hardware_profile'] = common_profiles.load_profile(
        root / '06_config/04_RCM/hardware_pins.yaml', 'RCM'
    ).data
    await RCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
