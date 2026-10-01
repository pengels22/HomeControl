from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_cfg = import_module('07_servises.common.config')

class PNLAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('PNL', config)
        self.room = config.get('room')
        self.dashboard_url = config.get('dashboard_url')

    async def collect_state(self):
        return {'room': self.room, 'dashboard_url': self.dashboard_url}

    async def apply_config(self, payload):
        result = await super().apply_config(payload)
        self.room = payload.get('room', self.room)
        self.dashboard_url = payload.get('dashboard_url', self.dashboard_url)
        return {**result, 'room': self.room, 'dashboard_url': self.dashboard_url}

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/05_PNL/pnl.yaml')
    await PNLAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
