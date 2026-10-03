from __future__ import annotations
import asyncio, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_can = import_module('07_servises.common.can')
common_cfg = import_module('07_servises.common.config')
common_io = import_module('07_servises.common.io')

class SIMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('SIM', config)
        self.rmc_nodes = {}
        self.io_mode = common_io.io_mode(config)
        self.can_network = common_can.SocketCANNetwork.from_config(config)
        self.rmc_sensor_stack = config.get('rmc_sensor_stack', common_can.RMC_SENSOR_DEFINITIONS)

    def _record_rmc_frame(self, interface, arbitration_id, data):
        self.can_network.record_frame(interface, arbitration_id, data)
        decoded = common_can.decode_rmc_frame(arbitration_id, data)
        if not decoded:
            return None
        addr = str(decoded['address'])
        node = self.rmc_nodes.setdefault(addr, {'address': decoded['address']})
        node['last_seen'] = time.time()
        node['last_frame_kind'] = decoded['kind']
        if decoded['kind'] == 'telemetry':
            node.update({
                'presence': decoded['presence'],
                'temperature_c': decoded['temperature_c'],
                'temperature_f': round(decoded['temperature_c'] * 9 / 5 + 32, 1),
                'humidity_pct': decoded['humidity_pct'],
                'lux': decoded['lux'],
                'aqi': decoded['aqi'],
                'sensor_ok': decoded['sensor_ok'],
                'sensor_faults': decoded['sensor_faults'],
                'any_sensor_fault': decoded['any_sensor_fault'],
            })
        elif decoded['kind'] == 'heartbeat':
            node.update({
                'protocol_version': decoded['protocol_version'],
                'fault_mask': decoded['fault_mask'],
                'faults': decoded['faults'],
                'status_flags': decoded['status_flags'],
                'uptime_s': decoded['uptime_s'],
            })
        elif decoded['kind'] in ('fault', 'fault_clear'):
            node.update({
                'fault_mask': decoded['fault_mask'],
                'faults': decoded['faults'],
                'status_flags': decoded['status_flags'],
                'fault_active': decoded['kind'] == 'fault',
            })
        return decoded

    async def collect_state(self):
        return {
            'rmc_nodes': self.rmc_nodes,
            'io_mode': self.io_mode,
            'can': self.can_network.snapshot(),
            'rmc_sensor_stack': self.rmc_sensor_stack,
            'last_scan': time.time(),
        }

    async def apply_command(self, payload):
        if payload.get('op') == 'configure_can':
            return {'ok': True, 'can': await self.can_network.configure(apply=bool(payload.get('apply', False)))}
        if payload.get('op') == 'inject_rmc_state':  # development/test helper
            addr = str(payload['address'])
            self.rmc_nodes[addr] = payload['state']
            return {'ok': True, 'address': addr}
        if payload.get('op') == 'inject_can_frame':  # development/test helper
            data = [int(v) for v in payload.get('data', [])]
            decoded = self._record_rmc_frame(payload['interface'], int(payload['arbitration_id']), data)
            return {'ok': True, 'interface': payload['interface'], 'decoded': decoded}
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    await SIMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
