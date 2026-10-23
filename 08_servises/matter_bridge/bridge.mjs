// HCM owns configuration and authorization. This process owns Matter transport only.
import { Endpoint, ServerNode, Environment, StorageService, Logger } from '@matter/main';
import { BridgedDeviceBasicInformationServer } from '@matter/main/behaviors/bridged-device-basic-information';
import { OnOffServer } from '@matter/main/behaviors/on-off';
import { LevelControlServer } from '@matter/main/behaviors/level-control';
import { OccupancySensingServer } from '@matter/main/behaviors/occupancy-sensing';
import { BooleanStateServer } from '@matter/main/behaviors/boolean-state';
import { OnOffLightDevice } from '@matter/main/devices/on-off-light';
import { DimmableLightDevice } from '@matter/main/devices/dimmable-light';
import { TemperatureSensorDevice } from '@matter/main/devices/temperature-sensor';
import { HumiditySensorDevice } from '@matter/main/devices/humidity-sensor';
import { OccupancySensorDevice } from '@matter/main/devices/occupancy-sensor';
import { ContactSensorDevice } from '@matter/main/devices/contact-sensor';
import { LightSensorDevice } from '@matter/main/devices/light-sensor';
import { AggregatorEndpoint } from '@matter/main/endpoints/aggregator';
import { createInterface } from 'node:readline';

// stdout is a private JSON protocol; keep SDK diagnostics on stderr.
Logger.getLoggerForIdentifier('default').log = (_level, message) => process.stderr.write(`${message}\n`);
const emit = message => process.stdout.write(`${JSON.stringify(message)}\n`);
const pending = new Map();
const endpoints = new Map();
let serial = 0;
function command(channelId, value, percent) {
    const id = ++serial;
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('HCM command timeout')); }, 12000);
        pending.set(id, { resolve, reject, timer });
        emit({ type: 'command', id, channel_id: channelId, value, percent });
    });
}

const MATTER_MAPPERS = Object.freeze({
    light: 'on_off_light', dimmable_light: 'dimmable_light',
    temperature_sensor: 'temperature_sensor', humidity_sensor: 'humidity_sensor',
    illuminance_sensor: 'illuminance_sensor', occupancy_sensor: 'occupancy_sensor',
    motion_sensor: 'occupancy_sensor', contact_sensor: 'contact_sensor',
});

function matterKind(row) {
    if (row.kind === 'light') return 'on_off_light';
    if (row.kind === 'dimmer') return 'dimmable_light';
    return MATTER_MAPPERS[row.capability] || null;
}

function deviceType(row) {
    const mapped = matterKind(row);
    class HcmOnOff extends OnOffServer {
        async on() { await command(row.channel_id, true); this.state.onOff = true; }
        async off() { await command(row.channel_id, false); this.state.onOff = false; }
    }
    if (mapped === 'on_off_light') return OnOffLightDevice.with(BridgedDeviceBasicInformationServer, HcmOnOff);
    class HcmLevel extends LevelControlServer {
        async moveToLevelLogic(level) {
            const percent = Math.max(0, Math.min(100, level * 100 / 254));
            await command(row.channel_id, percent > 0, percent);
            this.state.currentLevel = level;
        }
        move() { throw new Error('Use an absolute brightness level'); }
        moveWithOnOff() { throw new Error('Use an absolute brightness level'); }
        step() { throw new Error('Use an absolute brightness level'); }
        stepWithOnOff() { throw new Error('Use an absolute brightness level'); }
    }
    if (mapped === 'dimmable_light') return DimmableLightDevice.with(BridgedDeviceBasicInformationServer, HcmOnOff, HcmLevel);
    if (mapped === 'temperature_sensor') return TemperatureSensorDevice.with(BridgedDeviceBasicInformationServer);
    if (mapped === 'humidity_sensor') return HumiditySensorDevice.with(BridgedDeviceBasicInformationServer);
    if (mapped === 'occupancy_sensor') return OccupancySensorDevice.with(BridgedDeviceBasicInformationServer, OccupancySensingServer);
    if (mapped === 'contact_sensor') return ContactSensorDevice.with(BridgedDeviceBasicInformationServer, BooleanStateServer);
    if (mapped === 'illuminance_sensor') return LightSensorDevice.with(BridgedDeviceBasicInformationServer);
    throw new Error(`Unsupported canonical Matter capability: ${row.capability}`);
}

const storage = process.env.HCM_MATTER_STORAGE;
if (!storage) throw new Error('HCM_MATTER_STORAGE must name a persistent host-mounted directory');
Environment.default.vars.set('storage.path', storage);
const passcode = Number(process.env.HCM_MATTER_PASSCODE);
if (!Number.isInteger(passcode) || passcode <= 0) throw new Error('HCM_MATTER_PASSCODE is required');
const server = await ServerNode.create({
    id: 'homecontrol',
    network: { port: Number(process.env.HCM_MATTER_PORT || 5540) },
    commissioning: { passcode, discriminator: Number(process.env.HCM_MATTER_DISCRIMINATOR || 3840) },
    productDescription: { name: 'HomeControl', deviceType: AggregatorEndpoint.deviceType },
    basicInformation: { nodeLabel: 'HomeControl', productName: 'HomeControl development bridge', serialNumber: 'homecontrol-hcm' },
});
const aggregator = new Endpoint(AggregatorEndpoint, { id: 'aggregator', number: 1 });
await server.add(aggregator);

async function synchronize(rows) {
    const desired = new Map(rows.map(row => [row.entity_id || `channel_${row.channel_id}`, row]));
    for (const [id, entry] of endpoints) {
        if (!desired.has(id) || matterKind(desired.get(id)) !== entry.kind) {
            await entry.endpoint.close();
            endpoints.delete(id);
        }
    }
    for (const row of rows) {
        const entityId = row.entity_id || `channel_${row.channel_id}`;
        const mapped = matterKind(row);
        if (!mapped) continue;
        let entry = endpoints.get(entityId);
        const info = { nodeLabel: row.name.slice(0, 32), productName: row.name.slice(0, 32), reachable: row.available };
        if (!entry) {
            if (!Number.isInteger(row.endpoint) || row.endpoint < 2) throw new Error('Persistent endpoint allocation missing');
            const endpoint = new Endpoint(deviceType(row), {
                id: `hcm-entity-${entityId}`, number: row.endpoint,
                bridgedDeviceBasicInformation: { ...info, serialNumber: `hcm-entity-${entityId}` },
                ...(mapped === 'occupancy_sensor' ? { occupancySensing: { occupancySensorType: 0 } } : {}),
            });
            await aggregator.add(endpoint);
            entry = { endpoint, kind: mapped };
            endpoints.set(entityId, entry);
        } else {
            await entry.endpoint.set({ bridgedDeviceBasicInformation: info });
        }
        if (row.available && row.reported_state) {
            const state = { onOff: { onOff: row.reported_state.state === 'ON' } };
            if (mapped === 'dimmable_light' && Number.isFinite(row.reported_state.brightness)) {
                state.levelControl = { currentLevel: Math.round(row.reported_state.brightness * 254 / 100) };
            }
            await entry.endpoint.set(state);
        }
        if (row.capability === 'temperature_sensor' && row.current_state?.value != null) {
            await entry.endpoint.set({ temperatureMeasurement: { measuredValue: Math.round((row.current_state.value - 32) * 5 / 9 * 100) } });
        } else if (row.capability === 'humidity_sensor' && row.current_state?.value != null) {
            await entry.endpoint.set({ relativeHumidityMeasurement: { measuredValue: Math.round(row.current_state.value * 100) } });
        } else if (row.capability === 'illuminance_sensor' && row.current_state?.value != null) {
            const lux = Math.max(1, Number(row.current_state.value));
            await entry.endpoint.set({ illuminanceMeasurement: { measuredValue: Math.round(10000 * Math.log10(lux) + 1) } });
        } else if (row.capability === 'occupancy_sensor' || row.capability === 'motion_sensor') {
            await entry.endpoint.set({ occupancySensing: { occupancy: { occupied: Boolean(row.current_state?.value) } } });
        } else if (row.capability === 'contact_sensor' && row.current_state?.value != null) {
            await entry.endpoint.set({ booleanState: { stateValue: Boolean(row.current_state.value) } });
        }
    }
}
let queue = Promise.resolve();
const input = createInterface({ input: process.stdin });
input.on('line', line => {
    try {
        const message = JSON.parse(line);
        if (message.type === 'result') {
            const operation = pending.get(message.id);
            if (operation) {
                clearTimeout(operation.timer);
                pending.delete(message.id);
                if (message.ok) operation.resolve(); else operation.reject(new Error('HCM rejected command'));
            }
        } else if (message.type === 'registry') {
            queue = queue.then(() => synchronize(message.channels)).catch(error => { process.stderr.write(`${error}\n`); emit({type: 'error'}); });
        }
    } catch { process.stderr.write('Invalid HCM adapter message\n'); }
});
if (process.env.HCM_MATTER_VALIDATE_ONLY !== 'true') input.on('close', async () => { await server.close(); process.exit(0); });
process.on('SIGTERM', async () => { await server.close(); process.exit(0); });
if (process.env.HCM_MATTER_VALIDATE_ONLY === 'true') {
    await synchronize([
        {entity_id: 'channel_1', channel_id: 1, endpoint: 2, kind: 'light', capability: 'light', name: 'Validation light', available: false},
        {entity_id: 'channel_2', channel_id: 2, endpoint: 3, kind: 'dimmer', capability: 'dimmable_light', name: 'Validation dimmer', available: false},
        {entity_id: 'sensor_1', channel_id: 'sensor_1', endpoint: 4, capability: 'temperature_sensor', current_state: {value: 70, unit: '°F'}, name: 'Validation temperature', available: true},
        {entity_id: 'sensor_2', channel_id: 'sensor_2', endpoint: 5, capability: 'humidity_sensor', current_state: {value: 45, unit: '%'}, name: 'Validation humidity', available: true},
        {entity_id: 'sensor_3', channel_id: 'sensor_3', endpoint: 6, capability: 'illuminance_sensor', current_state: {value: 120, unit: 'lux'}, name: 'Validation illuminance', available: true},
        {entity_id: 'sensor_4', channel_id: 'sensor_4', endpoint: 7, capability: 'occupancy_sensor', current_state: {value: true}, name: 'Validation occupancy', available: true},
        {entity_id: 'sensor_5', channel_id: 'sensor_5', endpoint: 8, capability: 'contact_sensor', current_state: {value: false}, name: 'Validation contact', available: true},
    ]);
    await server.close();
    input.close();
    process.exit(0);
}
await server.start();
emit({ type: 'ready' });
