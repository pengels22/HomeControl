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

class RCMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('RCM', config)
        names = [f'{bank}{ch}' for bank in 'ABCD' for ch in range(1, 9)]
        pinout_path = config.get(
            'pinout_path',
            str(Path(__file__).resolve().parents[1] / '06_config/04_RCM/Pinout.md'),
        )
        self.pinout = common_pinmap.load_pinout(pinout_path)
        common_pinmap.require_channels(self.pinout, names)
        self.io_mode = common_io.io_mode(config)
        self.relays = common_hw.DigitalBank(names)
        self.fail_actions = config.get('fail_actions', {})

    async def collect_state(self):
        return {
            'relays': self.relays.snapshot(),
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
        }

    async def apply_command(self, payload):
        if payload.get('op') == 'set_relay':
            ch = payload['channel'].upper()
            self.relays.set(ch, bool(payload['value']))
            entry = self.pinout[ch]
            return {
                'ok': True,
                'channel': ch,
                'hardware_address': entry.hardware_address,
                'value': self.relays.get(ch),
            }
        if payload.get('op') == 'all_off':
            for ch in list(self.relays.values): self.relays.set(ch, False)
            return {'ok': True}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/04_RCM/rcm.yaml')
    await RCMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
