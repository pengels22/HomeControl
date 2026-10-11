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
- Signed Conflict responses in HMAC mode; device clients reject unsigned or
  tampered responses when authentication is configured.

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
channel. This is commissioning metadata only; installing or updating the local
`hcm-heartbeat.service` and its `/etc/hcm-heartbeat/config.json` remains a
separate deployment step.

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
`hmac-sha256` mode provides cryptographic request and response authentication
for staged lab validation using local secret files, but TLS certificate
issuance, certificate role constraints, and production listener publication
still require a separate approved deployment step.

Production must not silently downgrade to unauthenticated heartbeats. The staged
templates set `heartbeat_auth_mode=hmac-sha256` and require
`/etc/hcm-heartbeat/heartbeat-auth.secret`, provisioned outside Git with
restricted permissions. Missing or empty secrets fail closed at service startup.
Validate Conflict identity before publishing TCP 6004 beyond the protected lab
network.

## Deployment Compatibility

- Jetson currently runs Heartbeat V3 as an independent host service on Python
  3.6. `00_Heartbeat/hcm_heartbeat.py` remains standard-library Python 3.6
  compatible; do not introduce Python 3.7+ syntax in this daemon.
- Conflict stores supervision state in SQLite at
  `/var/lib/hcm-heartbeat/registry.sqlite3`. Preflight and backup scripts check
  this database without applying destructive migrations.
- The LAB1 installer mode only installs the heartbeat daemon files and
  `hcm-heartbeat.service`; it does not touch `homecontrol-lab.service`,
  `/opt/homecontrol-lab`, hostname, networking, certificates, commissioning
  state, or simulation role.

## Preflight Modes

`10_scripts/heartbeat_deployment_preflight.sh` is read-only and has two modes:

- `baseline`: inventory mode. It accepts and reports the currently installed
  configuration, including legacy unauthenticated configs. This mode is useful
  before cutover and does **not** approve the host for deployment.
- `strict`: deployment-readiness mode. It requires `hmac-sha256`, a present
  `heartbeat_auth_secret_file` with no group/world permissions, and matching
  deployment-critical fields between the installed config and the repository
  target template.

Run baseline before any installation attempt. Run strict only after the same
HMAC secret and matching config have been staged on the target host.

## Backup And Restore Safety

`10_scripts/heartbeat_backup.sh` uses SQLite's online backup API to copy
`registry.sqlite3` into a consistent standalone database while the heartbeat
service may still be writing. It intentionally does not independently copy
`registry.sqlite3-wal` or `registry.sqlite3-shm`, because those files are only
valid for the exact database state they accompany.

`10_scripts/heartbeat_rollback.sh` restores the backed-up database and removes
any existing WAL/SHM files before restarting the heartbeat service. This avoids
combining a restored database with stale live WAL content.

## Secure HMAC Secret Distribution

The staged HMAC secret must be generated and installed outside Git and outside
command-line arguments. Do not paste the secret into shell history, process
arguments, repository files, or documentation.

Recommended manual procedure for each target during an approved maintenance
window:

```bash
sudo install -d -m 0700 /etc/hcm-heartbeat
umask 077
sudo sh -c 'cat > /etc/hcm-heartbeat/heartbeat-auth.secret'
# paste or feed the secret through stdin from the operator's secure store, then EOF
sudo chown root:root /etc/hcm-heartbeat/heartbeat-auth.secret
sudo chmod 0600 /etc/hcm-heartbeat/heartbeat-auth.secret
```

Use the same secret bytes on Conflict, Jetson, and LAB1 for this staged HMAC
deployment. Verify with:

```bash
sudo stat -c '%U %G %a %n' /etc/hcm-heartbeat/heartbeat-auth.secret
sudo 10_scripts/heartbeat_deployment_preflight.sh strict conflict
```

On macOS during lab preparation, use equivalent `stat` syntax. Do not commit the
secret file or copy it into `/tmp`, chat transcripts, ticket systems, or command
arguments.

## Secure Cutover Sequence

The dangerous cutover edge is enabling required HMAC on Conflict before Jetson
has the same secret and matching client config. That would cause Conflict to
reject Jetson's existing plaintext heartbeat and create a Jetson-specific
`COMMUNICATION_LOSS` fault after the configured timeout.

Use this sequence to preserve monitoring:

1. On Conflict and Jetson, run baseline preflight and backup without changing
   services:
   `sudo 10_scripts/heartbeat_deployment_preflight.sh baseline conflict` and
   `sudo 10_scripts/heartbeat_backup.sh conflict` on Conflict, then the
   equivalent `baseline jetson` and `heartbeat_backup.sh jetson` on Jetson.
2. Provision the same HMAC secret file to both hosts with mode `0600`.
3. Stage the new configs on both hosts but do not restart either service yet.
4. Run strict preflight on both hosts against the staged installed configs.
5. Restart Jetson first only if Conflict still accepts legacy plaintext during
   the staging window. Otherwise schedule a paired restart window where Conflict
   and Jetson are restarted back-to-back and the timeout window is monitored.
6. Restart Conflict with the authenticated config.
7. Immediately verify Conflict `/status` and SQLite registry rows using
   `10_scripts/heartbeat_verify_readonly.sh http://127.0.0.1:6004`.
8. Confirm Jetson's registry entry remains device-specific and returns online
   before adding LAB1.
9. Install or restart LAB1 heartbeat only after Jetson is confirmed online under
   HMAC.

If either Conflict or Jetson fails after the restart:

- Do not modify networking, Docker, PostgreSQL, watchdog, or LAB1.
- Restore the failed host from the heartbeat backup using
  `10_scripts/heartbeat_rollback.sh <backup-dir>`.
- If Conflict was rolled back to plaintext, roll Jetson back to its matching
  prior heartbeat config before waiting for long-term health.
- Use baseline preflight after rollback to document the restored state, then
  repeat strict preflight before attempting the authenticated cutover again.

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
2. Provision `/etc/hcm-heartbeat/heartbeat-auth.secret` outside Git with mode
   `0600` before installing the fail-closed HMAC configuration.
3. Run `10_scripts/heartbeat_deployment_preflight.sh baseline conflict` on
   Conflict to record the currently installed state.
4. Stage the authenticated config and run
   `10_scripts/heartbeat_deployment_preflight.sh strict conflict`.
5. Install the updated Heartbeat V3 package on Conflict with the existing VLAN
   20 bind address.
6. Confirm `authorized_devices`, `communication_faults`, and event persistence.
7. Confirm Jetson remains individually tracked.

Rollback: stop `hcm-heartbeat.service`, restore backed-up files and config, move
the new SQLite DB aside if needed, and restart the service.

Stage B: Jetson compatibility

1. Keep the host `hcm-heartbeat.service` independent from Docker HCM.
2. Provision the same HMAC secret file outside Git.
3. Add expected Conflict device ID in config.
4. Validate direct Jetson-to-Conflict heartbeat and recovery behavior.

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
2. Provision the same HMAC secret file outside Git.
3. Run `HC_DRY_RUN=1 sudo ./install.sh lab1` to confirm the LAB1 installer path.
4. Install with `sudo ./install.sh lab1` during an approved maintenance window.
5. Do not change hostname, IP, VLAN, physical outputs, or simulation role.
6. Confirm LAB1 and Jetson appear as separate Conflict registry devices.

Rollback: stop LAB1 `hcm-heartbeat.service`, restore previous files if any, and
leave `homecontrol-lab.service` untouched.

## Known Limitations

- Production mTLS for Heartbeat V3 is not complete in this commit.
- HCM does not yet synchronize Conflict event cursors into the dashboard.
- Conflict administrative decommissioning APIs are not exposed yet.
- HCM commissioning provisions the verified Conflict endpoint metadata, but
  automatic installation/reconfiguration of the host heartbeat daemon is not
  implemented. Each processor still needs an approved heartbeat service
  deployment step.
- LAB1 installation and end-to-end loss/recovery validation require live LAB1 and
  Conflict access and explicit deployment approval.
