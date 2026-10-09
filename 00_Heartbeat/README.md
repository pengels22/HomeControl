# HCM Unified Heartbeat v3

One **Python 3.6+ standard-library-only** daemon on each device. Works on the Jetson's Ubuntu 18.04/Python 3.6 and current Armbian. One service, TCP 6004, including local fault/status/watchdog APIs.

## Architecture

- Device initiates `POST http://conflict:6004/heartbeat` every 5 seconds with hostname, IP, Ethernet MAC device ID, full health and status, sequence and boot ID.
- Conflict replies immediately with its own *full* health/status packet and echoes `reply_to` and `reply_boot_id` (not an empty ACK).
- Device treats any invalid/missed response as failure after 15 seconds; 45-second startup grace.
- Conflict keeps a registry, flags devices offline after 15 seconds, and returns its **own** health independently of peer health. This prevents failures cascading unnecessarily.
- Registry currently lives in memory and resets after Conflict restarts. Persisted **local fault/module states** survive restart; watchdog pulses intentionally do not.
- `GET /health` returns 200 or 503 for the **local device health**; `GET /status` always returns 200 including registry/peer details. Monitoring peers should inspect peer/registry state, not only the HTTP status.
- No authentication, by design. MAC/hostname are claims, not identity proof. Restrict TCP 6004 with VLAN/firewall; don't forward to the internet. An allowlist is a filtering aid, not security authentication.

## Installation (replace old services)

First stop old v1.x services on both hosts; keep the old configurations backed up if wanted:

On Jetson:
```
sudo systemctl disable --now hcm-heartbeat.service
sudo rm -f /etc/systemd/system/hcm-heartbeat.service
```
On Conflict:
```
sudo systemctl disable --now hcm-conflict-ack.service
sudo rm -f /etc/systemd/system/hcm-conflict-ack.service
```
The v3 installer installs a new service definition on each machine and leaves the old executables/config files untouched unless you clean them up separately. Importantly, it will preserve an **existing** `/etc/hcm-heartbeat/config.json`; remove or relocate the old v1.x config before installing v3 (see commands below).

Suggested Jetson migration (after copying package to `/tmp/hcm-heartbeat-v3`):
```
sudo mkdir -p /root/hcm-heartbeat-legacy
sudo cp -a /etc/hcm-heartbeat/config.json /root/hcm-heartbeat-legacy/ 2>/dev/null || true
sudo mv /etc/hcm-heartbeat/config.json /etc/hcm-heartbeat/config.legacy.json 2>/dev/null || true
cd /tmp/hcm-heartbeat-v3
sudo ./install.sh jetson
```
Conflict migration:
```
cd /tmp/hcm-heartbeat-v3
sudo ./install.sh conflict
```
On Conflict until Ethernet adapter is installed: `identity_interface` is `wlan0`, which provides a stable, lookupable MAC. Once `eth0` exists, change it to `eth0` and register its MAC in any monitored peers.

## Test

On Jetson:
```
curl -s http://127.0.0.1:6004/status | python3 -m json.tool
sudo hcm-heartbeat fault set test "Simulated HCM fault"
curl -i http://127.0.0.1:6004/health
sudo hcm-heartbeat fault clear test
sudo hcm-heartbeat status lighting operational
sudo hcm-heartbeat pulse sensors
```
On Conflict:
```
curl -s http://127.0.0.1:6004/status | python3 -m json.tool
sudo hcm-heartbeat show
```
To test dropped response: stop Conflict's v3 service for >=20s, then check Jetson status and restart it. `systemctl` automatically restarts on crashes, not deliberately stopped services.

## Future VLAN 60

On Conflict change `bind_address` and `advertise_ip` to `192.168.60.2`, change `identity_interface` to `eth0` when installed, and give `eth0.60` address `192.168.60.2/24` with proper routing/VLAN tagging. On devices change `conflict_address` to `192.168.60.2`. Their `advertise_ip` should be their actual heartbeat source IP. Restart after configuration changes. Do NOT change Conflict bind address before VLAN 60 is operational.

## Configuration

- `services`: monitored systemd unit names (only services genuinely installed on the system).
- `watchdogs`: object `{ "sensors": 10 }` means device must receive a `hcm-heartbeat pulse sensors` at least every 10 s. Configure and restart daemon before registering the actual sender.
- `allowed_device_ids`: MAC allowlist on Conflict. Empty list permits any sender (not recommended on shared networks).
- `conflict_device_id`: optional expected Conflict MAC for devices; fill it once physical interface ID is finalized.
- `maintenance_lockout`: boolean status only; does not suppress critical faults or disable life-safety logic.
- `identity_interface`: physical device interface read from `/sys/class/net/.../address`. It need not carry the heartbeat packets.

### Security / safety

All telemetry is unauthenticated and plaintext. It is suitable for a trusted, protected management VLAN, **not** as a safety interlock. Standalone fire/AC hardware handling must not rely on the network heartbeat. The systemd service runs root to read system service states and expose a controlled Unix socket (`/run/hcm-heartbeat/control.sock`, root/sudo-group write access). Command arguments are not executed as shell commands.
