from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('08_servises.common.agent')
common_cfg = import_module('08_servises.common.config')
common_global_config = import_module('08_servises.common.global_config')

class PNLAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('PNL', config)
        self.global_config = common_global_config.load_global_config('PNL')
        self.room = config.get('room')
        self.room_controls = []
        self.dashboard_url = config.get('dashboard_url')
        self.auto_refresh_interval_ms = int(config.get('auto_refresh_interval_ms', self.global_config.Panel_Auto_Refresh_Interval))
        self.default_brightness = int(config.get('default_brightness', self.global_config.Panel_Default_Brightness))
        self.require_authentication = bool(config.get('require_authentication', self.global_config.Panel_Require_Authentication))

    async def collect_state(self):
        return {
            'room': self.room,
            'room_controls': self.room_controls,
            'dashboard_url': self.dashboard_url,
            'display': {
                'auto_refresh_interval_ms': self.auto_refresh_interval_ms,
                'default_brightness': self.default_brightness,
                'require_authentication': self.require_authentication,
            },
        }

    async def apply_config(self, payload):
        if 'room_controls' in payload:
            self.room_controls = payload['room_controls']
            return {'ok': True, 'room_controls_contract': 1, 'controls': len(self.room_controls)}
        result = await super().apply_config(payload)
        self.room = payload.get('room', self.room)
        self.dashboard_url = payload.get('dashboard_url', self.dashboard_url)
        self.auto_refresh_interval_ms = int(payload.get('auto_refresh_interval_ms', self.auto_refresh_interval_ms))
        self.default_brightness = int(payload.get('default_brightness', self.default_brightness))
        self.require_authentication = bool(payload.get('require_authentication', self.require_authentication))
        return {**result, 'room': self.room, 'dashboard_url': self.dashboard_url}

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '07_config/05_PNL/pnl.yaml')
    await PNLAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
