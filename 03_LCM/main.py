from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('08_servises.common.agent')
common_cfg = import_module('08_servises.common.config')
common_hw = import_module('08_servises.common.hardware')
common_io = import_module('08_servises.common.io')
common_global_config = import_module('08_servises.common.global_config')
common_safety = import_module('08_servises.common.safety_arbiter')
common_infra = import_module('08_servises.common.module_infra')
common_profiles = import_module('08_servises.common.hardware_profiles')
common_commissioning = import_module('08_servises.common.commissioning')
common_drivers = import_module('08_servises.common.physical_drivers')
common_factory = import_module('08_servises.common.hardware_factory')
state_confidence = import_module('08_servises.common.state_confidence')

class LCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('LCM', config)
        self.global_config = common_global_config.load_global_config('LCM')
        self.hardware_profile = config.get('hardware_profile', {})
        if not isinstance(self.hardware_profile, dict):
            root = Path(__file__).resolve().parents[1]
            self.hardware_profile = common_profiles.load_profile(
                root / '07_config/03_LCM/hardware_pins.yaml', 'LCM'
            ).data
        self.relay_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_RELAY_CHANNELS, start=1)}
        self.lv_dimmer_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_ANALOG_DIMMER_CHANNELS, start=9)}
        self.hv_dimmer_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_HV_DIMMER_CHANNELS, start=19)}
        self.io_mode = common_io.io_mode(config)
        hardware_mode = 'mock' if config.get('mock_hardware') else self.io_mode
        self.driver_bundle = common_factory.build_hardware_bundle('LCM', {**config, 'hardware_mode': hardware_mode}, self.hardware_profile)
        if self.driver_bundle.mode in {'simulated', 'disabled'}:
            self.driver_bundle = None
        if self.driver_bundle:
            self.driver_bundle['lcm_relays'].initialize()
            self.driver_bundle['lcm_pwm'].initialize()
        self.relays = common_hw.DigitalBank(common_infra.LCM_RELAY_CHANNELS)
        self.lv_dimmers = common_hw.AnalogOutputs(common_infra.LCM_ANALOG_DIMMER_CHANNELS)
        self.hv_dimmers = common_hw.AnalogOutputs(common_infra.LCM_HV_DIMMER_CHANNELS)
        self.i2c = config.get('i2c', {})
        self.i2c_bus = common_hw.I2CBus(
            int(self.i2c.get('bus', 1)),
            enabled=bool(self.i2c.get('enabled', False)) and common_io.real_io_enabled(config),
        )
        self.peripherals.register('lcm_pwm_controller', name='0-10V PWM Controller', category='i2c', metadata={'real_output_enabled': False, 'model': None})
        self.peripherals.components['lcm_pwm_controller'].status = 'not_configured'
        self.peripherals.register('shelly_hv_1', name='Shelly Pro Dimmer 1', category='network_io', metadata={'real_output_enabled': False})
        self.peripherals.components['shelly_hv_1'].status = 'not_configured'
        self.peripherals.register('shelly_hv_2', name='Shelly Pro Dimmer 2', category='network_io', metadata={'real_output_enabled': False})
        self.peripherals.components['shelly_hv_2'].status = 'not_configured'
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

    def _clamp_percent(self, value):
        return max(
            float(self.global_config.Lighting_Dimmer_Min_Percent),
            min(float(self.global_config.Lighting_Dimmer_Max_Percent), float(value)),
        )

    def _safety_requires_output_shutdown(self, conditions):
        return any(bool((conditions or {}).get(name)) for name in (
            'maintenance_lockout',
            'fire_input_fault',
            'communication_loss',
            'arbiter_fault',
        ))

    def _deenergize_all_outputs_for_safety(self):
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
            if self.io_mode == 'real' and self.driver_bundle and self.driver_bundle.get('lcm_relays'):
                try:
                    self.driver_bundle['lcm_relays'].set_channel(self._relay_index(ch), False)
                except Exception as exc:
                    logging.getLogger(__name__).exception('failed to deenergize relay %s', ch)
                    failures.append({'channel': ch, 'error': str(exc)})
            decisions.append(decision.as_dict())
        for bank in (self.hv_dimmers, self.lv_dimmers):
            for ch in list(bank.values):
                decision = self.safety.decide(common_safety.OutputRequest(
                    self.identity.get('device_id'),
                    ch,
                    {'op': 'set_dimmer', 'channel': ch, 'percent': 0, 'value': False, 'source': 'safety_state'},
                    'safety_state',
                ))
                bank.set_percent(ch, float(decision.final_command.get('percent', 0.0)))
                if self.io_mode == 'real':
                    try:
                        self._physical_dimmer_off(ch)
                    except Exception as exc:
                        logging.getLogger(__name__).exception('failed to deenergize dimmer %s', ch)
                        failures.append({'channel': ch, 'error': str(exc)})
                decisions.append(decision.as_dict())
        return {'decisions': decisions, 'failures': failures, 'safe_state_attempted': self.io_mode == 'real'}

    async def collect_state(self):
        return {
            'relays': self.relays.snapshot(),
            'hv_dimmers': self.hv_dimmers.snapshot(),
            'lv_dimmers': self.lv_dimmers.snapshot(),
            'channel_inventory': {
                'relays': common_infra.LCM_RELAY_CHANNELS,
                'analog_dimmers': common_infra.LCM_ANALOG_DIMMER_CHANNELS,
                'hv_dimmers': common_infra.LCM_HV_DIMMER_CHANNELS,
            },
            'i2c': {
                'enabled': bool(self.i2c.get('enabled', False)),
                'io_mode': self.io_mode,
                'real_bus_active': self.i2c_bus.enabled,
                'bus': self.i2c_bus.bus_id,
                'analog_pwm_contract': 'TBD',
                'analog_real_output_enabled': False,
            },
            'network_io': {
                'shelly_contract': 'TBD',
                'shelly_real_output_enabled': False,
            },
            'hardware_profile': {
                'verification': self.hardware_profile.get('verification', {}),
                'physical_output_enabled': self.hardware_profile.get('physical_output_enabled', False),
                'commissioning': common_commissioning.commissioning_status(
                    self.hardware_profile,
                    common_infra.LCM_RELAY_CHANNELS + common_infra.LCM_ANALOG_DIMMER_CHANNELS + common_infra.LCM_HV_DIMMER_CHANNELS,
                ),
            },
            'safety': self.safety.snapshot(),
            'hardware_drivers': {
                name: driver.diagnostics()
                for name, driver in (self.driver_bundle or {}).items()
                if hasattr(driver, 'diagnostics')
            } or {'mode': 'not_instantiated'},
            'state_confidence_label': state_confidence.COMMANDED if self.io_mode == 'real' else state_confidence.SIMULATED,
        }

    def _percent(self, payload):
        raw = payload.get('percent', payload.get('value', 100))
        if isinstance(raw, bool):
            return 100.0 if raw else 0.0
        return float(raw)

    def _command_confidence(self, physical_requested, kind):
        if physical_requested:
            return state_confidence.DEVICE_REPORTED if kind == 'hv_dimmer' else state_confidence.OUTPUT_LATCH_READBACK
        return state_confidence.COMMANDED if self.io_mode == 'real' else state_confidence.SIMULATED

    def _normalize_channel(self, channel):
        value = str(channel).strip().upper()
        if value in self.relays.values or value in self.lv_dimmers.values or value in self.hv_dimmers.values:
            return value
        return self.relay_map.get(value) or self.lv_dimmer_map.get(value) or self.hv_dimmer_map.get(value) or value

    def _relay_index(self, channel):
        return common_infra.LCM_RELAY_CHANNELS.index(channel)

    def _hv_mapping(self, channel):
        mapping = (self.hardware_profile.get('outputs', {}).get('hv_dimmers', {}).get('mappings', {}) or {}).get(channel)
        if not isinstance(mapping, dict):
            raise KeyError(channel)
        return str(mapping['device_slot']), str(mapping['component'])

    def _physical_dimmer_off(self, channel):
        if channel in self.lv_dimmers.values:
            if not self.driver_bundle or not self.driver_bundle.get('lcm_pwm'):
                raise RuntimeError('PCA9685 driver is not configured')
            return self.driver_bundle['lcm_pwm'].set_percent(common_infra.LCM_ANALOG_DIMMER_CHANNELS.index(channel), 0)
        slot, component = self._hv_mapping(channel)
        driver = self.driver_bundle.get(slot) if self.driver_bundle else None
        if not driver:
            raise RuntimeError(f'{slot} Shelly driver is not configured')
        return driver.set_brightness(component, 0)

    def _set_channel(self, channel, payload):
        logical = self._normalize_channel(channel)
        if logical in self.relays.values:
            physical = logical
            physical_requested = bool(payload.get('physical_write_requested'))
            if physical_requested and self.io_mode != 'real':
                return {'ok': False, 'error': 'io_mode_not_real', 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            if physical_requested and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': common_commissioning.physical_write_denial_reason(self.hardware_profile, physical), 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, payload, payload.get('source', 'module_api')))
            if physical_requested:
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                self.driver_bundle['lcm_relays'].set_channel(self._relay_index(physical), bool(decision.final_command.get('value', False)))
            self.relays.set(physical, bool(decision.final_command.get('value', False)))
            return {'ok': True, 'kind': 'relay', 'channel': logical, 'physical': physical, 'value': self.relays.get(physical), 'physical_output_commanded': physical_requested, 'state_confidence_label': self._command_confidence(physical_requested, 'relay'), 'arbitration': decision.as_dict()}
        if logical in self.hv_dimmers.values:
            physical = logical
            physical_requested = bool(payload.get('physical_write_requested'))
            if physical_requested and self.io_mode != 'real':
                return {'ok': False, 'error': 'io_mode_not_real', 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            if physical_requested and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': common_commissioning.physical_write_denial_reason(self.hardware_profile, physical), 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, bounded, payload.get('source', 'module_api')))
            if physical_requested:
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                slot, component = self._hv_mapping(physical)
                self.driver_bundle[slot].set_brightness(component, float(decision.final_command.get('percent', 0)))
            self.hv_dimmers.set_percent(physical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'hv_dimmer', 'channel': logical, 'physical': physical, **self.hv_dimmers.snapshot()[physical], 'physical_output_commanded': physical_requested, 'state_confidence_label': self._command_confidence(physical_requested, 'hv_dimmer'), 'arbitration': decision.as_dict()}
        if logical in self.lv_dimmers.values:
            physical = logical
            physical_requested = bool(payload.get('physical_write_requested'))
            if physical_requested and self.io_mode != 'real':
                return {'ok': False, 'error': 'io_mode_not_real', 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            if physical_requested and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': common_commissioning.physical_write_denial_reason(self.hardware_profile, physical), 'channel': logical, 'physical_outputs_commanded': False, 'state_confidence_label': state_confidence.UNKNOWN}
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, bounded, payload.get('source', 'module_api')))
            if physical_requested:
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                self.driver_bundle['lcm_pwm'].set_percent(common_infra.LCM_ANALOG_DIMMER_CHANNELS.index(physical), float(decision.final_command.get('percent', 0)))
            self.lv_dimmers.set_percent(physical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'lv_dimmer', 'channel': logical, 'physical': physical, **self.lv_dimmers.snapshot()[physical], 'physical_output_commanded': physical_requested, 'state_confidence_label': self._command_confidence(physical_requested, 'lv_dimmer'), 'arbitration': decision.as_dict()}
        raise KeyError(logical)

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
                        if not self.driver_bundle or not self.driver_bundle.get('lcm_relays'):
                            raise RuntimeError('physical driver unavailable')
                        self.driver_bundle['lcm_relays'].set_channel(self._relay_index(ch), False)
                    self.relays.set(ch, False)
                except Exception as exc:
                    failures.append({'channel': ch, 'error': str(exc)})
            return {'ok': not failures, 'failures': failures, 'attempted': sorted(targets)}

        op = payload.get('op')
        if op == 'safety_state':
            conditions = payload.get('conditions', {})
            self.safety.update_conditions(conditions)
            result = self._deenergize_all_outputs_for_safety() if self._safety_requires_output_shutdown(conditions) else {'decisions': [], 'failures': [], 'safe_state_attempted': False}
            return {'ok': not result['failures'], 'safety': self.safety.snapshot(), 'arbitration': result['decisions'], 'safe_state_attempted': result['safe_state_attempted'], 'failures': result['failures']}
        if op in ('set_channel', 'light') or ('channel' in payload and 'value' in payload):
            return self._set_channel(payload['channel'], payload)
        if op == 'set_relay':
            return self._set_channel(payload.get('relay', payload['channel']), {**payload, 'percent': 100 if payload.get('value') else 0})
        if op == 'set_dimmer':
            return self._set_channel(payload.get('dimmer', payload['channel']), payload)
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    root = Path(__file__).resolve().parents[1]
    cfg = common_cfg.load_yaml(root / '07_config/03_LCM/lcm.yaml')
    cfg['hardware_profile'] = common_profiles.load_profile(
        root / '07_config/03_LCM/hardware_pins.yaml', 'LCM'
    ).data
    await LCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
