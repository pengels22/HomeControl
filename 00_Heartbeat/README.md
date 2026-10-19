# HCM Unified Heartbeat V3

Unified Heartbeat V3 is the independent HomeControl supervision service.

Architecture authority: [Network, Communications, and Supervision white paper](../09_documentation/whitepapers/NETWORK_AND_HEARTBEAT.md).

## Current deployment

Current development/supervision network: **VLAN 20**.

Known active identities/addresses:

- Jetson/HCM primary Ethernet: `192.168.20.27`
- Jetson/HCM Wi-Fi: `192.168.20.25`
- Conflict Manager primary Ethernet: `192.168.20.26`
- Conflict Manager Wi-Fi: `192.168.20.24`
- TCP port: `6004`

Conflict's stable device ID is derived from its designated identity interface. The interface supplying identity does not have to carry heartbeat traffic.

VLAN 60 is not part of the current approved architecture.

## Roles

### Device role

A device:

- builds a local health/status snapshot;
- sends it to Conflict every configured interval;
- includes hostname, stable device ID, boot ID, sequence, timestamp, health, and status;
- validates Conflict's authenticated response;
- tracks acknowledgement freshness.

### Conflict role

Conflict:

- accepts authorized device heartbeats;
- validates authentication and message shape;
- rejects replayed sequence numbers for the same boot;
- records device restart and duplicate-ID events;
- maintains current reachability and communication-loss faults;
- persists its registry/history in SQLite;
- returns its own independent health/status snapshot.

## Authentication

Heartbeat V3 supports:

- `none` for isolated lab compatibility;
- `hmac-sha256` for authenticated request/response operation.

The current secured architecture uses HMAC-SHA256 with a local secret file.

When HMAC mode is selected, missing secret material is a startup/configuration failure.

MAC address, hostname, and IP address are operational identity fields; they are not cryptographic proof by themselves.

## Replay and acknowledgement checks

Conflict tracks:

- boot ID;
- last accepted sequence;
- observed source;
- last-seen time.

For a matching boot ID, a sequence less than or equal to the last accepted sequence is rejected.

The sending device validates:

- protocol/version;
- response authentication;
- `reply_to`;
- `reply_boot_id`;
- expected Conflict hostname;
- expected Conflict device ID;
- health/status structure.

## Local control socket

Local applications can report status, faults, and watchdog pulses through:

`/run/hcm-heartbeat/control.sock`

Supported concepts include:

- set/clear external fault;
- set subsystem status;
- watchdog pulse;
- read snapshot.

This lets HCM/module application state be supervised without making the application itself the heartbeat server.

## Health endpoints

Heartbeat V3 exposes:

- `GET /health` — local device health;
- `GET /status` — complete local/status/peer or registry information.

Consumers should inspect peer/registry data for remote reachability rather than inferring it from the local HTTP status alone.

## Installation/deployment

Use the repository deployment framework rather than historical V1/V2 migration instructions.

Current deployment references:

- [Jetson HCM deployment](../09_documentation/JETSON_HCM_DEPLOYMENT_2026-10-10.md)
- [Unified configuration/deployment framework](../09_documentation/UNIFIED_CONFIGURATION_DEPLOYMENT_2026-10-11.md)

Do not replace or restart an otherwise healthy Heartbeat V3 service as a side effect of ordinary HCM container updates.

## Basic inspection

Examples:

```sh
curl -s http://127.0.0.1:6004/status | python3 -m json.tool
sudo hcm-heartbeat show
sudo hcm-heartbeat fault set test "test fault"
sudo hcm-heartbeat fault clear test
```

Use deliberate maintenance procedures before testing actual communication loss on live hosts.

## Configuration highlights

Important keys include:

- `role`
- `port`
- `bind_address`
- `advertise_ip`
- `identity_interface`
- `state_file`
- `registry_db`
- `socket_path`
- `services`
- `watchdogs`
- `interval_seconds`
- `peer_timeout_seconds`
- `startup_grace_seconds`
- `conflict_address`
- `conflict_hostname`
- `allowed_device_ids`
- `authorized_devices`
- `heartbeat_auth_mode`
- `heartbeat_auth_secret_file`
- `max_timestamp_skew_seconds`
- `conflict_device_id`

Secret files must not be committed.

## Safety boundary

Heartbeat is supervision, not life-safety output authority.

Fire and AC-present dry contacts remain independently sensed. Network heartbeat must never be the only mechanism used to authorize or clear a fire condition.
