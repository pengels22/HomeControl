from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_cfg = import_module('07_servises.common.config')
common_hw = import_module('07_servises.common.hardware')

class LCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('LCM', config)
        self.relay_map = {str(i): f'A{i}' for i in range(1, 9)}
        self.relay_map.update({str(i): f'B{i - 8}' for i in range(9, 13)})
        self.hv_dimmer_map = {str(i): f'HV-{i - 12}' for i in range(13, 17)}
        self.lv_dimmer_map = {str(i): f'10-{i - 16}' for i in range(17, 25)}
        self.relays = common_hw.DigitalBank(sorted(set(self.relay_map.values())))
        self.hv_dimmers = common_hw.AnalogOutputs(sorted(set(self.hv_dimmer_map.values())))
        self.lv_dimmers = common_hw.AnalogOutputs([f'10-{i}' for i in range(1, 9)])

    async def collect_state(self):
        return {
            'relays': self.relays.snapshot(),
            'hv_dimmers': self.hv_dimmers.snapshot(),
            'lv_dimmers': self.lv_dimmers.snapshot(),
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
            self.relays.set(physical, bool(payload.get('value', self._percent(payload) > 0)))
            return {'ok': True, 'kind': 'relay', 'channel': logical, 'physical': physical, 'value': self.relays.get(physical)}
        if logical in self.relays.values:
            self.relays.set(logical, bool(payload.get('value', self._percent(payload) > 0)))
            return {'ok': True, 'kind': 'relay', 'channel': logical, 'value': self.relays.get(logical)}
        if logical in self.hv_dimmer_map:
            physical = self.hv_dimmer_map[logical]
            self.hv_dimmers.set_percent(physical, self._percent(payload))
            return {'ok': True, 'kind': 'hv_dimmer', 'channel': logical, 'physical': physical, **self.hv_dimmers.snapshot()[physical]}
        if logical in self.lv_dimmer_map:
            physical = self.lv_dimmer_map[logical]
            self.lv_dimmers.set_percent(physical, self._percent(payload))
            return {'ok': True, 'kind': 'lv_dimmer', 'channel': logical, 'physical': physical, **self.lv_dimmers.snapshot()[physical]}
        if logical in self.lv_dimmers.values:
            self.lv_dimmers.set_percent(logical, self._percent(payload))
            return {'ok': True, 'kind': 'lv_dimmer', 'channel': logical, **self.lv_dimmers.snapshot()[logical]}
        raise KeyError(logical)

    async def apply_command(self, payload):
        op = payload.get('op')
        if op in ('set_channel', 'light') or ('channel' in payload and 'value' in payload):
            return self._set_channel(payload['channel'], payload)
        if op == 'set_relay':
            return self._set_channel(payload.get('relay', payload['channel']), {**payload, 'percent': 100 if payload.get('value') else 0})
        if op == 'set_dimmer':
            return self._set_channel(payload.get('dimmer', payload['channel']), payload)
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/03_LCM/lcm.yaml')
    await LCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
