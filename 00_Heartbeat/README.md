# HCM Unified Heartbeat v3

## Verified Ethernet-first deployment (2026-10-10)

The Jetson remains on the current VLAN 20 development network: primary `eth0=192.168.20.27`, secondary `wlan0=192.168.20.25`. Conflict Manager uses primary USB Ethernet `enx6c6e07545f03=192.168.20.26` and secondary `wlan0=192.168.20.24`. Conflict's `identity_interface=wlan0` and device ID `3c53bbf7adb2` are **intentional** even though traffic uses USB Ethernet. Jetson `identity_interface=eth0`, advertises `192.168.20.27`, and sends to Conflict `192.168.20.26:6004`. Live Conflict /status verified Jetson online/healthy with recent heartbeat. Legacy instructions below to change Conflict identity to `eth0` or move to `192.168.60.2` describe **future migration only**; do not apply them to this live installation. HCM application work must not restart or alter this independent host daemon. See [Phase 4 implementation contract](../09_documentation/PHASE4_CODEX_IMPLEMENTATION_2026-10-10.md).


## Live Jetson deployment clarification (2026-10-10)

The independent host-based `hcm-heartbeat.service` (Python 3.6, TCP 6004) was confirmed active after a complete Jetson reboot alongside the Dockerized HCM application. The 2026-10-10 installation still uses the existing VLAN 20/Conflict addressing; **VLAN 60 migration is not complete**. Do not replace or restart Heartbeat V3 as part of HCM container updates. See [Jetson runbook](../09_documentation/JETSON_HCM_DEPLOYMENT_2026-10-10.md) for current service boundaries. Older passages below describe historic migrations and may not match the installed state.


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

## VLAN 60 Heartbeat Network

VLAN 60 is permanently reserved for heartbeat/supervisory traffic. On Conflict,
change `bind_address` and `advertise_ip` to `192.168.60.2`, change
`identity_interface` to `eth0` when installed, and give `eth0.60` address
`192.168.60.2/24` with proper routing/VLAN tagging. On devices change
`conflict_address` to `192.168.60.2`. Their `advertise_ip` should be their
actual heartbeat source IP. Restart after configuration changes. Do NOT change
Conflict bind address before VLAN 60 is operational.

VLAN 20 remains the current development/control network. VLAN 40 is the future
production control network, but its subnet is not approved yet.

## Configuration

- `services`: monitored systemd unit names (only services genuinely installed on the system).
- `watchdogs`: object `{ "sensors": 10 }` means device must receive a `hcm-heartbeat pulse sensors` at least every 10 s. Configure and restart daemon before registering the actual sender.
- `allowed_device_ids`: device ID allowlist on Conflict. Target format is the normalized designated-interface MAC address, lowercase with colons removed. Empty list permits any sender, which is not recommended on shared networks.
- `conflict_device_id`: optional expected Conflict device ID for devices; fill it once physical interface ID is finalized.
- `maintenance_lockout`: boolean status only; does not suppress critical faults or disable life-safety logic.
- `identity_interface`: physical device interface read from `/sys/class/net/.../address`. It need not carry the heartbeat packets. Target device IDs are normalized to 12 lowercase hexadecimal characters without colons.

### Security / safety

All telemetry is unauthenticated and plaintext. It is suitable for a trusted, protected management VLAN, **not** as a safety interlock. Standalone fire/AC hardware handling must not rely on the network heartbeat. The systemd service runs root to read system service states and expose a controlled Unix socket (`/run/hcm-heartbeat/control.sock`, root/sudo-group write access). Command arguments are not executed as shell commands.
