#!/usr/bin/env python3
"""LAB1 local emergency configuration server.

This process serves the local administrator UI only. It never opens the HCM
module TCP session and never calls an output driver; LAB1 remains simulation-only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ModuleAgent = import_module('07_servises.common.agent').ModuleAgent


class Lab1EmergencyAgent(ModuleAgent):
    def __init__(self) -> None:
        state_path = Path('/opt/homecontrol-lab/state/module.json')
        super().__init__('LCM', {
            'identity_path': str(state_path),
            'runtime_root': '/opt/homecontrol-lab/state/homecontrol',
            'software_version': 'lab1-emergency-ui',
            'web': {'enabled': True, 'host': '0.0.0.0', 'port': 6010},
        })
        self.state_path = state_path

    async def web_status(self):
        status = await super().web_status()
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            state = {}
        status['identity'].update({
            'device_id': state.get('device_id', '2ccf675d3414'),
            'hostname': state.get('hostname', 'lab1'),
            'role': state.get('role', 'UNASSIGNED'),
            'simulation': state.get('simulation') is True,
            'physical_outputs_enabled': state.get('physical_outputs_enabled') is True,
        })
        status['simulation'] = state.get('simulation') is True
        status['physical_outputs_enabled'] = state.get('physical_outputs_enabled') is True
        status['hcm_connection_mode'] = 'reported by LAB1 role agent'
        return status


async def main() -> None:
    agent = Lab1EmergencyAgent()
    await agent._run_web()


if __name__ == '__main__':
    asyncio.run(main())
