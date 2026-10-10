# HCM Heartbeat Spec

> **Status note (2026-10-10):** The independent native Unified Heartbeat V3 service on Jetson remained active through HCM commissioning and automatically returned active after a full Jetson reboot (2026-10-10). HCM runs separately in Docker; neither its Docker container nor database should become a requirement for the host heartbeat. VLAN 60 is still a future staged migration. See [Jetson runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md).


This document describes Unified Heartbeat V3 as implemented in `00_Heartbeat/`.
It also identifies conflicts with the separate HCM/module heartbeat currently
implemented under `07_servises/common/agent.py` and `01_HCM/registry.py`.

## Scope

Unified Heartbeat V3 is a Python 3.6+ standard-library-only daemon. It is
intended to run as one service per participating processor, including the
Conflict Manager and devices such as the Jetson/HCM.

It is supervisory telemetry. It is not cryptographic authentication and must not
be used as the sole authorization path for safety-critical actions.

## Transport

Implemented transport:

- HTTP over plaintext TCP.
- Default port: TCP 6004.
- Device role sends `POST /heartbeat` to the Conflict Manager.
- Both roles expose `GET /health` and `GET /status`.
- Both roles expose a local Unix control socket at
  `/run/hcm-heartbeat/control.sock`.

The current implementation does not use TLS or message authentication.

## Roles

### Device Role

A device role:

- Builds a full local heartbeat snapshot every `interval_seconds`.
- Sends it to `http://<conflict_address>:<port>/heartbeat`.
- Validates the Conflict Manager's full heartbeat response.
- Tracks `last_ack`, `peer_health`, and `last_error`.
- Marks the Conflict Manager peer offline after `peer_timeout_seconds`, except
  during `startup_grace_seconds`.

### Conflict Role

A conflict role:

- Accepts `POST /heartbeat`.
- Validates protocol, version, hostname, sequence, health, status, and MAC-like
  device ID shape.
- Optionally filters by `allowed_device_ids`.
- Records peer heartbeat details in an in-memory registry.
- Returns its own full local snapshot plus `reply_to` and `reply_boot_id`.
- Marks peers online/offline in registry based on heartbeat age.

Peer faults are intentionally stored in registry status, not folded into the
Conflict Manager's own health.

## Packet Fields

Implemented snapshot fields:

- `protocol`: always `hcm-heartbeat`.
- `version`: integer `3`.
- `hostname`: local hostname from `socket.gethostname()`.
- `ip_address`: configured `advertise_ip`, outbound source IP for device role,
  or bind address for conflict role.
- `device_id`: target architecture requires the normalized MAC address read
  from configured `identity_interface`, lowercase with colons removed. Current
  code still emits colon-form MACs and must be updated before normalized
  allowlists are enforced.
- `identity_interface`: interface used for device ID.
- `boot_id`: UUID generated on daemon start.
- `sequence`: heartbeat sequence number.
- `timestamp`: Unix wall-clock seconds.
- `health`:
  - `state`: currently `healthy` or `fault`.
  - `faults`: list of system, service, external, watchdog, or peer faults.
  - `system`: memory, disk, and thermal metrics.
  - `services`: configured systemd service states.
- `status`:
  - `state`: currently `operational` or `degraded`.
  - `uptime_seconds`: host uptime.
  - `modules`: locally reported module/subsystem states.
  - `maintenance_lockout`: configured status flag.
  - `peer`: Conflict response status for device role.
  - `registry`: Conflict role only, per-peer records.

Conflict replies add:

- `reply_to`: received device sequence.
- `reply_boot_id`: received device boot ID.

## Health And Fault Logic

Implemented local fault sources:

- Memory below `min_available_memory_percent`.
- Root disk use at or above `root_disk_percent_fail`.
- Highest thermal zone at or above `thermal_celsius_fail`.
- Configured systemd service inactive.
- Locally submitted external faults.
- Configured watchdog pulse overdue or never received.
- Conflict Manager peer response overdue for device role after startup grace.

Implemented states:

- Health is `healthy` when there are no local faults, otherwise `fault`.
- Status is `operational` when there are no local faults, otherwise `degraded`.
- Registry entries include online booleans, heartbeat age, last sequence, peer
  health, and peer status.

The architecture brief calls for `healthy`, `degraded`, `faulted`, and
`offline` distinctions. The current V3 code partially implements this concept
but names local faulted health as `fault`, and uses registry `online` booleans
for reachability.

## Local Control Interface

The CLI sends JSON over the Unix socket. Implemented actions:

- `fault set <name> <value>` -> persistent external fault.
- `fault clear <name>` -> clears persistent external fault.
- `status <name> <value>` -> persistent module/subsystem status.
- `pulse <name>` -> non-persistent watchdog pulse.
- `show` -> snapshot.

The service runs as root to inspect systemd state and creates the socket with
mode `0660`, attempting group ownership by `sudo`.

## Persistence

Persisted to `state_file`:

- External faults.
- Module/subsystem status entries.

Persisted on the Conflict Manager to SQLite `registry_db`:

- Device registration by normalized `device_id`.
- First seen and last seen timestamps.
- Last hostname, advertised IP, observed source IP, boot ID, sequence, health,
  and status.
- Current communication reachability and offline transition time.
- Heartbeat, registration, online, offline, and duplicate-ID events.

Not persisted:

- Watchdog pulses.
- Boot ID.
- Sequence number.
- Last acknowledgment/error state.

After Conflict restart, persisted devices remain available as last-known state
but are marked not currently reachable until they heartbeat again.

## Configuration

Important config keys:

- `role`: `device` or `conflict`.
- `port`: default `6004`.
- `bind_address`: default `0.0.0.0`.
- `advertise_ip`: optional explicit IP in packets.
- `identity_interface`: default `eth0`.
- `state_file`: default `/var/lib/hcm-heartbeat/state.json`.
- `registry_db`: default `/var/lib/hcm-heartbeat/registry.sqlite3`.
- `socket_path`: default `/run/hcm-heartbeat/control.sock`.
- `services`: systemd units to monitor.
- `watchdogs`: name-to-timeout map.
- `interval_seconds`: default `5`.
- `peer_timeout_seconds`: default `15`.
- `startup_grace_seconds`: default `45`.
- `request_timeout_seconds`: default `4`.
- `conflict_address`: default `192.168.20.26`.
- `conflict_hostname`: default `conflict`.
- `allowed_device_ids`: optional allowlist; target format is normalized 12-hex
  MAC IDs after the V3 code is updated.
- `conflict_device_id`: optional expected Conflict MAC; target format is
  normalized 12-hex.
- `maintenance_lockout`: status flag only.

Device ID is a normalized MAC read from `identity_interface`. The identity
interface does not need to carry heartbeat traffic.

## Current Device Configs

`00_Heartbeat/config-jetson.json` and `config-conflict.json` should be treated
as deployment examples for the current V3 development baseline on VLAN 20. Do
not change them to bind to VLAN 60 until `eth0.60`, VLAN tagging, routing, and
source IP selection are verified. Do not switch allowlists to normalized IDs
until `hcm_heartbeat.py` emits normalized IDs.

## VLAN 60 Migration

VLAN 60 is the permanent heartbeat/supervisory network between modules/devices
and the Conflict Manager. The V3 migration is:

- Conflict `bind_address` and `advertise_ip` become `192.168.60.2`.
- Conflict `identity_interface` changes to `eth0` once installed.
- Devices change `conflict_address` to `192.168.60.2`.
- Device `advertise_ip` should match the real heartbeat source IP.
- Device IDs and allowlists use normalized MAC IDs.
- Do not change Conflict bind address before VLAN 60 is operational.

The original repository used VLAN 60 as the HCM module control network with HCM
at `192.168.60.1` and modules in `.20+` pools. The registry now uses
configurable control-network profiles instead; VLAN 20 is the active development
profile, VLAN 40 remains disabled until approved values exist, and VLAN 60 is
heartbeat/supervisory only.

## Separate Module Heartbeat Conflict

The HCM/module stack currently implements a different heartbeat:

- Persistent TCP session to HCM port 6501.
- Optional TLS.
- Length-prefixed JSON frames.
- Module sends `heartbeat` frames.
- HCM writes `last_state`, `last_seen`, and sends `heartbeat_ack`.
- HCM marks module offline when the TCP session closes.

This is useful for module state/control, but it is not Unified Heartbeat V3.
Future reconciliation should decide whether:

- V3 becomes the network-wide health/supervision plane while TCP 6501 remains
  command/state transport, or
- Linux modules also run V3 and report module health through the local Unix
  socket, with TCP 6501 heartbeats reduced to session liveness.

Do not reintroduce older V1/V2 ACK daemons or create additional competing
heartbeat services.

## Security Notes

Current V3 heartbeat packets are unauthenticated and plaintext. MAC address,
hostname, and IP address identify devices operationally but do not prove
identity. Restrict TCP 6004 to approved hosts and networks; never expose it to
the public Internet.
