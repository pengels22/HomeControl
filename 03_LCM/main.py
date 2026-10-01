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
        self.relays = common_hw.DigitalBank([f'{bank}{ch}' for bank in 'ABCD' for ch in range(1, 9)])
        self.dimmers = common_hw.AnalogOutputs([f'10-{i}' for i in range(1, 9)])

    async def collect_state(self):
        return {'relays': self.relays.snapshot(), 'dimmers': self.dimmers.snapshot()}

    async def apply_command(self, payload):
        op = payload.get('op')
        if op == 'set_relay':
            ch = payload['channel'].upper(); self.relays.set(ch, bool(payload['value']))
            return {'ok': True, 'channel': ch, 'value': self.relays.get(ch)}
        if op == 'set_dimmer':
            ch = payload['channel']; self.dimmers.set_percent(ch, float(payload['percent']))
            return {'ok': True, 'channel': ch, **self.dimmers.snapshot()[ch]}
        if op == 'light':
            relay = payload['relay'].upper(); dimmer = payload.get('dimmer')
            pct = float(payload.get('percent', 100))
            if pct <= 0:
                if dimmer: self.dimmers.set_percent(dimmer, 0)
                self.relays.set(relay, False)
            else:
                self.relays.set(relay, True)
                if dimmer: self.dimmers.set_percent(dimmer, pct)
            return {'ok': True}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/03_LCM/lcm.yaml')
    await LCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
