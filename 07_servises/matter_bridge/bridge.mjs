// HCM owns configuration and authorization. This process owns Matter transport only.
import { Endpoint, ServerNode, Environment, StorageService, Logger } from '@matter/main';
import { BridgedDeviceBasicInformationServer } from '@matter/main/behaviors/bridged-device-basic-information';
import { OnOffServer } from '@matter/main/behaviors/on-off';
import { LevelControlServer } from '@matter/main/behaviors/level-control';
import { OnOffLightDevice } from '@matter/main/devices/on-off-light';
import { DimmableLightDevice } from '@matter/main/devices/dimmable-light';
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

function deviceType(row) {
    class HcmOnOff extends OnOffServer {
        async on() { await command(row.channel_id, true); this.state.onOff = true; }
        async off() { await command(row.channel_id, false); this.state.onOff = false; }
    }
    if (row.kind === 'light') return OnOffLightDevice.with(BridgedDeviceBasicInformationServer, HcmOnOff);
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
    return DimmableLightDevice.with(BridgedDeviceBasicInformationServer, HcmOnOff, HcmLevel);
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
    const desired = new Map(rows.map(row => [row.channel_id, row]));
    for (const [id, entry] of endpoints) {
        if (!desired.has(id) || desired.get(id).kind !== entry.kind) {
            await entry.endpoint.close();
            endpoints.delete(id);
        }
    }
    for (const row of rows) {
        let entry = endpoints.get(row.channel_id);
        const info = { nodeLabel: row.name.slice(0, 32), productName: row.name.slice(0, 32), reachable: row.available };
        if (!entry) {
            if (!Number.isInteger(row.endpoint) || row.endpoint < 2) throw new Error('Persistent endpoint allocation missing');
            const endpoint = new Endpoint(deviceType(row), {
                id: `hcm-channel-${row.channel_id}`, number: row.endpoint,
                bridgedDeviceBasicInformation: { ...info, serialNumber: `hcm-channel-${row.channel_id}` },
            });
            await aggregator.add(endpoint);
            entry = { endpoint, kind: row.kind };
            endpoints.set(row.channel_id, entry);
        } else {
            await entry.endpoint.set({ bridgedDeviceBasicInformation: info });
        }
        if (row.available && row.reported_state) {
            const state = { onOff: { onOff: row.reported_state.state === 'ON' } };
            if (row.kind === 'dimmer' && Number.isFinite(row.reported_state.brightness)) {
                state.levelControl = { currentLevel: Math.round(row.reported_state.brightness * 254 / 100) };
            }
            await entry.endpoint.set(state);
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
    await synchronize([{channel_id: 1, endpoint: 2, kind: 'light', name: 'Validation light', available: false}, {channel_id: 2, endpoint: 3, kind: 'dimmer', name: 'Validation dimmer', available: false}]);
    await server.close();
    input.close();
    process.exit(0);
}
await server.start();
emit({ type: 'ready' });
