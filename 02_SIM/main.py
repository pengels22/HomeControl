from __future__ import annotations
import asyncio, logging, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importlib import import_module
common_agent = import_module('07_servises.common.agent')
common_can = import_module('07_servises.common.can')
common_cfg = import_module('07_servises.common.config')
common_io = import_module('07_servises.common.io')
common_rmc_fw = import_module('07_servises.common.rmc_firmware')

class SIMAgent(common_agent.ModuleAgent):
    def __init__(self, config):
        super().__init__('SIM', config)
        self.rmc_nodes = {}
        self.io_mode = common_io.io_mode(config)
        self.can_network = common_can.SocketCANNetwork.from_config(config)
        self.rmc_sensor_stack = config.get('rmc_sensor_stack', common_can.RMC_SENSOR_DEFINITIONS)
        self.hexa_board = config.get('hexa_board', {})
        self.hexa_dio_state = self._initial_output_state('dio', 'channels')
        self.hexa_switching_state = self._initial_output_state('switching_12v', 'outputs')
        self.hexa_usb_links = {}
        self.rmc_firmware_cfg = config.get('rmc_firmware_updates', {})
        self.firmware_staging_root = Path(self.rmc_firmware_cfg.get('staging_root', '/var/lib/hcm/firmware-staging'))
        self.compatible_rmc_hardware = list(self.rmc_firmware_cfg.get('compatible_hardware', ['RMC-NANO-ATMEGA328P']))
        self.rmc_update_sessions = {}

    def _hexa_section(self, section):
        return self.hexa_board.get('interfaces', {}).get(section, {})

    def _initial_output_state(self, section, child_key):
        items = self._hexa_section(section).get(child_key, {})
        return {name: bool(item.get('simulated', False)) for name, item in items.items()}

    def _analog_value_status(self, item):
        value = float(item.get('simulated_v', item.get('nominal_v', 0)))
        off_below = item.get('off_below_v')
        low = item.get('warning_low_v')
        high = item.get('warning_high_v')
        off = off_below is not None and value < float(off_below)
        ok = not off and (low is None or value >= float(low)) and (high is None or value <= float(high))
        status = 'OFF' if off else 'OK' if ok else 'FAULT'
        return {
            'label': item.get('label'),
            'source': item.get('source'),
            'unit': item.get('unit', 'V'),
            'value': value,
            'status': status,
            'visible': bool(item.get('visible', True)),
            'nominal_v': item.get('nominal_v'),
            'off_below_v': off_below,
            'warning_low_v': low,
            'warning_high_v': high,
            'ok': ok,
        }

    def hexa_state(self):
        aio = self._hexa_section('aio')
        bus_monitors = aio.get('bus_monitors', {})
        loop_monitors = aio.get('loop_monitors', {})
        analog_inputs = aio.get('analog_inputs', {})
        dio = self._hexa_section('dio').get('channels', {})
        switching = self._hexa_section('switching_12v').get('outputs', {})
        usb = self._hexa_section('usb').get('ports', {})
        bus = {name: self._analog_value_status(item) for name, item in bus_monitors.items()}
        loops = {name: self._analog_value_status(item) for name, item in loop_monitors.items()}
        ai = {name: self._analog_value_status(item) for name, item in analog_inputs.items()}
        return {
            'model': self.hexa_board.get('model'),
            'role': self.hexa_board.get('role'),
            'aio': {
                'ads1115': aio.get('ads1115', []),
                'bus_monitors': bus,
                'loop_monitors': loops,
                'analog_inputs': ai,
            },
            'dio': {
                name: {
                    'label': item.get('label'),
                    'direction': item.get('direction', 'input'),
                    'value': self.hexa_dio_state.get(name, bool(item.get('simulated', False))),
                }
                for name, item in dio.items()
            },
            'usb': self.hexa_usb_state(usb),
            'switching_12v': {
                name: {
                    'label': item.get('label'),
                    'value': self.hexa_switching_state.get(name, bool(item.get('simulated', False))),
                    'restart_count': int(item.get('restart_count', 0)),
                }
                for name, item in switching.items()
            },
            'can': self.can_network.snapshot(),
            'all_bus_monitors_ok': all(item['status'] in ('OK', 'OFF') for item in {**bus, **loops}.values()),
        }

    def hexa_usb_state(self, ports):
        linked_ports = {item['port'] for item in self.hexa_usb_links.values()}
        return {
            'ports': {
                name: {
                    'label': item.get('label', name),
                    'available': name not in linked_ports,
                }
                for name, item in ports.items()
            },
            'available_ports': [
                {'id': name, 'label': item.get('label', name)}
                for name, item in ports.items()
                if name not in linked_ports
            ],
            'linked_devices': list(self.hexa_usb_links.values()),
        }

    def link_hexa_usb(self, name, port):
        ports = self._hexa_section('usb').get('ports', {})
        if port not in ports:
            return {'ok': False, 'error': 'unknown_hexa_usb_port'}
        if any(item['port'] == port for item in self.hexa_usb_links.values()):
            return {'ok': False, 'error': 'hexa_usb_port_already_linked'}
        clean_name = str(name).strip()[:80]
        if not clean_name:
            return {'ok': False, 'error': 'missing_device_name'}
        link_id = str(uuid.uuid4())
        link = {
            'id': link_id,
            'name': clean_name,
            'port': port,
            'port_label': ports[port].get('label', port),
        }
        self.hexa_usb_links[link_id] = link
        return {'ok': True, 'link': link}

    def disconnect_hexa_usb(self, link_id):
        link = self.hexa_usb_links.pop(str(link_id), None)
        if not link:
            return {'ok': False, 'error': 'unknown_hexa_usb_link'}
        return {'ok': True, 'disconnected': link}

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
            'hexa_board': self.hexa_state(),
            'rmc_sensor_stack': self.rmc_sensor_stack,
            'rmc_firmware_updates': {
                'enabled': bool(self.rmc_firmware_cfg.get('enabled', True)),
                'staging_root': str(self.firmware_staging_root),
                'sessions': {k: v.to_dict() for k, v in self.rmc_update_sessions.items()},
            },
            'last_scan': time.time(),
        }

    async def perform_rmc_firmware_update(self, payload):
        package = payload['package']
        target = payload.get('target', {})
        session_id = str(package.get('session_id') or payload.get('session_id'))
        node_id = int(target.get('node_id', payload.get('node_id')))
        can_interface = str(target.get('can_interface', payload.get('can_interface', 'can0')))
        target_rmc_id = str(target.get('rmc_id', payload.get('target_rmc_id', f'RMC-{node_id:02d}')))
        if can_interface not in self.can_network.interfaces:
            return {'ok': False, 'error': f'unknown CAN interface {can_interface}'}

        session = common_rmc_fw.RmcFirmwareUpdateSession(
            session_id=session_id,
            target_rmc_id=target_rmc_id,
            node_id=node_id,
            can_interface=can_interface,
            firmware_version=str(package.get('firmware_version', 'unknown')),
        )
        self.rmc_update_sessions[session_id] = session
        try:
            session.transition('RECEIVING_FIRMWARE', 0)
            session.transition('VALIDATING_PACKAGE', 5)
            image = common_rmc_fw.validate_package(package, compatible_hardware=self.compatible_rmc_hardware)
            staged_path = common_rmc_fw.stage_package(self.firmware_staging_root, package, image)
            session.transition('READY', 10, {'staged_path': str(staged_path)})
            session.transition('REQUESTING_BOOTLOADER', 12)
            session.transition('WAITING_FOR_BOOTLOADER', 15)
            session.transition('BEGINNING_UPDATE', 20)
            frames = common_rmc_fw.update_frame_plan(image, node_id, session_id)
            data_frames = [frame for frame in frames if frame['command'] == 'UPDATE_DATA']
            session.transition('TRANSFERRING', 25, {'blocks': len(data_frames)})
            iface = self.can_network.interfaces[can_interface]
            total_data = max(1, len(data_frames))
            for frame in frames:
                iface.tx_count += 1
                iface.last_frame = {
                    'arbitration_id': frame['arbitration_id'],
                    'data': frame['data'],
                    'ts': time.time(),
                    'firmware_update': True,
                    'command': frame['command'],
                }
                session.frames_sent += 1
                if frame['command'] == 'UPDATE_DATA':
                    seq = int(frame['sequence'])
                    pct = 25 + int(((seq + 1) / total_data) * 50)
                    if pct >= session.progress_pct + 10 or seq == total_data - 1:
                        session.transition('TRANSFERRING', pct, {'sequence': seq})
                await asyncio.sleep(0)
            session.transition('VERIFYING', 80, {'crc32': package.get('image_crc32')})
            session.transition('REBOOTING', 90)
            session.transition('WAITING_FOR_APPLICATION', 94)
            node = self.rmc_nodes.setdefault(str(node_id), {'address': node_id})
            node.update({
                'firmware_version': package.get('firmware_version'),
                'hardware_revision': package.get('hardware_revision'),
                'last_seen': time.time(),
                'last_frame_kind': 'application_online',
            })
            session.transition('VERIFYING_VERSION', 98, {'reported_version': node['firmware_version']})
            if node['firmware_version'] != package.get('firmware_version'):
                raise RuntimeError('VERSION_MISMATCH')
            session.transition('COMPLETE', 100)
            try:
                staged_path.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                'ok': True,
                'session': session.to_dict(),
                'reported_firmware_version': node['firmware_version'],
                'frames_sent': session.frames_sent,
            }
        except Exception as exc:
            session.error = str(exc)
            session.transition('FAILED', session.progress_pct, {'error': session.error})
            return {'ok': False, 'session': session.to_dict(), 'error': session.error}

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
        if payload.get('op') == 'set_hexa_dio':
            channel = str(payload['channel'])
            if channel not in self.hexa_dio_state:
                return {'ok': False, 'error': 'unknown_hexa_dio_channel'}
            self.hexa_dio_state[channel] = bool(payload.get('value', False))
            return {'ok': True, 'channel': channel, 'value': self.hexa_dio_state[channel]}
        if payload.get('op') == 'set_hexa_12v':
            channel = str(payload['channel'])
            if channel not in self.hexa_switching_state:
                return {'ok': False, 'error': 'unknown_hexa_12v_channel'}
            self.hexa_switching_state[channel] = bool(payload.get('value', False))
            return {'ok': True, 'channel': channel, 'value': self.hexa_switching_state[channel]}
        if payload.get('op') == 'restart_hexa_12v':
            channel = str(payload['channel'])
            if channel not in self.hexa_switching_state:
                return {'ok': False, 'error': 'unknown_hexa_12v_channel'}
            self.hexa_switching_state[channel] = False
            await asyncio.sleep(float(payload.get('delay_s', 0)))
            self.hexa_switching_state[channel] = True
            return {'ok': True, 'channel': channel, 'value': True, 'restarted': True}
        if payload.get('op') == 'link_hexa_usb':
            return self.link_hexa_usb(payload.get('name', ''), str(payload.get('port', '')))
        if payload.get('op') == 'disconnect_hexa_usb':
            return self.disconnect_hexa_usb(payload.get('id', ''))
        if payload.get('op') == 'rmc_firmware_update':
            return await self.perform_rmc_firmware_update(payload)
        return await super().apply_command(payload)

async def main():
    logging.basicConfig(level=logging.INFO)
    cfg = common_cfg.load_yaml(Path(__file__).resolve().parents[1] / '06_config/02_SIM/sim.yaml')
    await SIMAgent(cfg).run()

if __name__ == '__main__': asyncio.run(main())
