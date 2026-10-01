from __future__ import annotations
import asyncio, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_cfg = import_module('07_servises.common.config')

class SIMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('SIM', config)
        self.rmc_nodes = {}

    async def collect_state(self):
        # CAN integration point: replace this dictionary with MCP2515/RMC frames.
        return {'rmc_nodes': self.rmc_nodes, 'last_scan': time.time()}

    async def apply_command(self, payload):
        if payload.get('op') == 'inject_rmc_state':  # development/test helper
            addr = str(payload['address'])
            self.rmc_nodes[addr] = payload['state']
            return {'ok': True, 'address': addr}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    await SIMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
