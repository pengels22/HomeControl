# Universal Conflict Heartbeat Supervision

Status: development foundation implemented in the repository only. Nothing in
this document has been deployed to Conflict, Jetson, or LAB1.

## Audit Summary

Reviewed implementation and deployment references:

- `00_Heartbeat/hcm_heartbeat.py`
- `00_Heartbeat/install.sh`
- `00_Heartbeat/hcm-heartbeat.service`
- `00_Heartbeat/config-conflict.json`
- `00_Heartbeat/config-jetson.json`
- `00_Heartbeat/README.md`
- `01_HCM/registry.py`
- `01_HCM/settings.py`
- `01_HCM/api.py`
- `06_config/common/install_module.sh`
- `07_servises/common/agent.py`
- `07_servises/systemd/homecontrol-module@.service`
- `08_database/schema.sql`
- `09_documentation/architecture/HCM_HEARTBEAT_SPEC.md`
- `09_documentation/architecture/HCM_ARCHITECTURE_CONFLICTS.md`
- `10_scripts/lab1_role_agent.py`
- `11_tests/test_heartbeat_v3.py`
- Registry, identity, LAB1 role-switching, and management API tests.

Findings:

- Heartbeat V3 already runs independently from HCM and uses SQLite on Conflict,
  but prior behavior could auto-register first heartbeat observations.
- The prior allowlist behavior was a filter, not authentication. Empty
  allowlists could accept arbitrary devices.
- Conflict did not persist active/resolved communication-loss faults as durable
  lifecycle records.
- HCM had no module-control payload for Conflict endpoint provisioning.
- LAB1 had a safe HCM-control connection and role switching, but no repository
  LAB1 heartbeat config artifact for direct LAB1-to-Conflict supervision.

## Implemented Foundation

Conflict heartbeat supervision now includes:

- `authorized_devices` SQLite table for durable authorization state.
- `communication_faults` SQLite table for active and resolved
  `COMMUNICATION_LOSS` lifecycle records.
- Startup `supervisor_restart` event records.
- Config-seeded authorization from `allowed_device_ids` and
  `authorized_devices`.
- Rejection of unknown or inactive devices, including when the allowlist is
  empty.
- Per-device replay rejection for repeated or older sequence numbers within the
  same boot session.
- Duplicate reachable identity detection for simultaneous sources.
- Device reboot detection when boot identity changes.
- Communication-loss detection with deterministic active-fault deduplication.
- Recovery resolution when a valid heartbeat returns.
- Independent Conflict monitor loop; timeout evaluation no longer depends on a
  dashboard request or another incoming heartbeat.
- Optional `hmac-sha256` request authentication using a local secret file.

HCM module provisioning now includes a `heartbeat_supervisor` block in config
responses:

```json
{
  "enabled": true,
  "device_id": "3c53bbf7adb2",
  "host": "192.168.20.26",
  "port": 6004,
  "interval_seconds": 5,
  "timeout_seconds": 15,
  "protocol": "hcm-heartbeat-v3"
}
```

The module agent persists this endpoint metadata in its identity file. It does
not receive private keys, passwords, or shared secrets through the HCM control
channel.

## Current LAB Configuration

Repository templates remain on VLAN 20:

- Conflict: `192.168.20.26:6004`, device ID `3c53bbf7adb2`
- Jetson: `192.168.20.27`, device ID `48b02d87db16`
- LAB1: `192.168.20.36`, device ID `2ccf675d3414`

`00_Heartbeat/config-conflict.json` now authorizes Jetson and LAB1 separately.
`00_Heartbeat/config-lab1.json` provides a separately installable LAB1
heartbeat client configuration. It does not alter LAB1 hostname, IP, VLAN,
device identity, commissioning state, simulation lockout, or physical outputs.

## Security Boundary

This commit does not claim a completed production mTLS rollout. The implemented
`hmac-sha256` mode provides cryptographic request authentication for staged lab
validation using local secret files, but TLS certificate issuance, certificate
role constraints, and production listener publication still require a separate
approved deployment step.

Production must not silently downgrade to unauthenticated heartbeats. For a
secure rollout, configure `heartbeat_auth_mode=hmac-sha256` or the future mTLS
mode on both device and Conflict, store secrets or certificates outside Git, and
validate Conflict identity before publishing TCP 6004 beyond the protected lab
network.

## Timeout Behavior

- Default interval: 5 seconds.
- Default timeout: 15 seconds.
- A device is considered overdue when `last_seen < now - timeout_seconds`.
- Conflict creates one active `COMMUNICATION_LOSS` fault per active device.
- Further monitor cycles do not duplicate active faults.
- A valid authenticated heartbeat resolves the active fault and retains history.
- Conflict restart records `supervisor_restart` and retains registrations and
  fault history.

## Deployment Plan

Stage A: Conflict foundation

1. Back up `/etc/hcm-heartbeat/config.json`,
   `/usr/local/lib/hcm-heartbeat/hcm_heartbeat.py`,
   `/usr/local/lib/hcm-heartbeat/homecontrol_identity.py`, and
   `/var/lib/hcm-heartbeat/registry.sqlite3`.
2. Install the updated Heartbeat V3 package on Conflict with the existing VLAN
   20 bind address.
3. Confirm `authorized_devices`, `communication_faults`, and event persistence.
4. Confirm Jetson remains individually tracked.

Rollback: stop `hcm-heartbeat.service`, restore backed-up files and config, move
the new SQLite DB aside if needed, and restart the service.

Stage B: Jetson compatibility

1. Keep the host `hcm-heartbeat.service` independent from Docker HCM.
2. Add expected Conflict device ID in config.
3. Validate direct Jetson-to-Conflict heartbeat and recovery behavior.

Rollback: restore previous Jetson heartbeat config and script only. Do not
restart HCM or PostgreSQL for heartbeat rollback.

Stage C: HCM provisioning

1. Deploy the HCM code that includes `heartbeat_supervisor` config.
2. Confirm module identity and assignment behavior are unchanged.
3. Confirm modules persist the supervisor endpoint metadata.

Rollback: redeploy the prior HCM image. Module-local persisted endpoint metadata
is inert unless the module heartbeat service consumes it.

Stage D: LAB1 direct heartbeat

1. Copy the repository heartbeat package to LAB1.
2. Install with `sudo ./install.sh lab1` during an approved maintenance window.
3. Do not change hostname, IP, VLAN, physical outputs, or simulation role.
4. Confirm LAB1 and Jetson appear as separate Conflict registry devices.

Rollback: stop LAB1 `hcm-heartbeat.service`, restore previous files if any, and
leave `homecontrol-lab.service` untouched.

## Known Limitations

- Production mTLS for Heartbeat V3 is not complete in this commit.
- HCM does not yet synchronize Conflict event cursors into the dashboard.
- Conflict administrative decommissioning APIs are not exposed yet.
- LAB1 installation and end-to-end loss/recovery validation require live LAB1 and
  Conflict access and explicit deployment approval.
