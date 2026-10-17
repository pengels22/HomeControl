from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_cfg = import_module('07_servises.common.config')
common_hw = import_module('07_servises.common.hardware')
common_io = import_module('07_servises.common.io')
common_global_config = import_module('07_servises.common.global_config')
common_safety = import_module('07_servises.common.safety_arbiter')
common_infra = import_module('07_servises.common.module_infra')
common_profiles = import_module('07_servises.common.hardware_profiles')
common_commissioning = import_module('07_servises.common.commissioning')
common_drivers = import_module('07_servises.common.physical_drivers')

class LCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('LCM', config)
        self.global_config = common_global_config.load_global_config('LCM')
        self.hardware_profile = config.get('hardware_profile', {})
        if not isinstance(self.hardware_profile, dict):
            root = Path(__file__).resolve().parents[1]
            self.hardware_profile = common_profiles.load_profile(
                root / '06_config/03_LCM/hardware_pins.yaml', 'LCM'
            ).data
        self.relay_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_RELAY_CHANNELS, start=1)}
        self.lv_dimmer_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_ANALOG_DIMMER_CHANNELS, start=9)}
        self.hv_dimmer_map = {str(i): channel for i, channel in enumerate(common_infra.LCM_HV_DIMMER_CHANNELS, start=19)}
        self.io_mode = common_io.io_mode(config)
        self.driver_bundle = common_drivers.build_lab1_mock_drivers() if config.get('mock_hardware') else None
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
        for ch in list(self.relays.values):
            decision = self.safety.decide(common_safety.OutputRequest(
                self.identity.get('device_id'),
                ch,
                {'op': 'set_relay', 'channel': ch, 'value': False, 'source': 'safety_state'},
                'safety_state',
            ))
            self.relays.set(ch, bool(decision.final_command.get('value', False)))
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
                decisions.append(decision.as_dict())
        return decisions

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
        }

    def _percent(self, payload):
        raw = payload.get('percent', payload.get('value', 100))
        if isinstance(raw, bool):
            return 100.0 if raw else 0.0
        return float(raw)

    def _set_channel(self, channel, payload):
        logical = str(channel).upper()
        if logical in self.relay_map:
            physical = self.relay_map[logical]
            if payload.get('physical_write_requested') and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': 'physical channel is not explicitly commissioned', 'channel': logical, 'physical_outputs_commanded': False}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, payload, payload.get('source', 'module_api')))
            if payload.get('physical_write_requested'):
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                self.driver_bundle['lcm_relays'].set_channel(int(physical) - 1, bool(decision.final_command.get('value', False)))
            self.relays.set(physical, bool(decision.final_command.get('value', False)))
            return {'ok': True, 'kind': 'relay', 'channel': logical, 'physical': physical, 'value': self.relays.get(physical), 'arbitration': decision.as_dict()}
        if logical in self.relays.values:
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), logical, payload, payload.get('source', 'module_api')))
            self.relays.set(logical, bool(decision.final_command.get('value', False)))
            return {'ok': True, 'kind': 'relay', 'channel': logical, 'value': self.relays.get(logical), 'arbitration': decision.as_dict()}
        if logical in self.hv_dimmer_map:
            physical = self.hv_dimmer_map[logical]
            if payload.get('physical_write_requested') and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': 'physical channel is not explicitly commissioned', 'channel': logical, 'physical_outputs_commanded': False}
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, bounded, payload.get('source', 'module_api')))
            if payload.get('physical_write_requested'):
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                self.driver_bundle['shelly_1' if int(physical) < 21 else 'shelly_2'].set_brightness(
                    f"light:{(int(physical) - 19) % 2}", float(decision.final_command.get('percent', 0))
                )
            self.hv_dimmers.set_percent(physical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'hv_dimmer', 'channel': logical, 'physical': physical, **self.hv_dimmers.snapshot()[physical], 'arbitration': decision.as_dict()}
        if logical in self.hv_dimmers.values:
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), logical, bounded, payload.get('source', 'module_api')))
            self.hv_dimmers.set_percent(logical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'hv_dimmer', 'channel': logical, **self.hv_dimmers.snapshot()[logical], 'arbitration': decision.as_dict()}
        if logical in self.lv_dimmer_map:
            physical = self.lv_dimmer_map[logical]
            if payload.get('physical_write_requested') and not common_commissioning.physical_write_allowed(self.hardware_profile, physical):
                return {'ok': False, 'error': 'physical channel is not explicitly commissioned', 'channel': logical, 'physical_outputs_commanded': False}
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), physical, bounded, payload.get('source', 'module_api')))
            if payload.get('physical_write_requested'):
                if not self.driver_bundle:
                    return {'ok': False, 'error': 'physical driver is not configured', 'channel': logical, 'physical_outputs_commanded': False}
                self.driver_bundle['lcm_pwm'].set_percent(int(physical) - 9, float(decision.final_command.get('percent', 0)))
            self.lv_dimmers.set_percent(physical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'lv_dimmer', 'channel': logical, 'physical': physical, **self.lv_dimmers.snapshot()[physical], 'arbitration': decision.as_dict()}
        if logical in self.lv_dimmers.values:
            bounded = {**payload, 'percent': self._clamp_percent(self._percent(payload))}
            decision = self.safety.decide(common_safety.OutputRequest(self.identity.get('device_id'), logical, bounded, payload.get('source', 'module_api')))
            self.lv_dimmers.set_percent(logical, float(decision.final_command.get('percent', 0.0)))
            return {'ok': True, 'kind': 'lv_dimmer', 'channel': logical, **self.lv_dimmers.snapshot()[logical], 'arbitration': decision.as_dict()}
        raise KeyError(logical)

    async def apply_command(self, payload):
        op = payload.get('op')
        if op == 'safety_state':
            conditions = payload.get('conditions', {})
            self.safety.update_conditions(conditions)
            decisions = self._deenergize_all_outputs_for_safety() if self._safety_requires_output_shutdown(conditions) else []
            return {'ok': True, 'safety': self.safety.snapshot(), 'arbitration': decisions}
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
    cfg = common_cfg.load_yaml(root / '06_config/03_LCM/lcm.yaml')
    cfg['hardware_profile'] = common_profiles.load_profile(
        root / '06_config/03_LCM/hardware_pins.yaml', 'LCM'
    ).data
    await LCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
