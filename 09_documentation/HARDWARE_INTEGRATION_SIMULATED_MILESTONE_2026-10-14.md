# Hardware Integration Simulated Milestone - 2026-10-14

This branch adds shared simulated infrastructure for HomeControl module health,
configuration persistence, structured event logging, and Git-backed HCM storage.
No production hardware, firmware, Conflict service, LAB1 role, VLAN, database schema,
or deployed Jetson service was changed.

## Implemented in Simulation

- Shared I2C component inventory for the verified relay cards and MCP expanders:
  `0x20`, `0x21`, `0x26`, and `0x27`.
- RCM physical relay mapping for A1-D8 across Relay Card 1 and Relay Card 2.
- LCM runtime inventory corrected to 8 relays, 10 analog 0-10V dimmers, and 4 HV dimmers.
- Commanded-state reporting explicitly marks RCM relay state as commanded-only with no contact feedback.
- Common module status, health, HCM-authenticated status endpoints, and offline local-admin emergency configuration endpoints.
- Default module emergency web port changed to `6010`.
- Local JSONL structured event logger with duplicate suppression after the third repeated non-safety event.
- Offline event queue with idempotent enqueue and delivery removal.
- Local configuration store, including strict RCM CSV schema: `Channel ID,Name,on,Lockout`.
- HCM `/var/lib/homecontrol` storage layout helper with local Git initialization.
- ADMIN-only HCM Git settings endpoints and Settings UI controls with PAT redaction.

## Persistence, Git, and Offline Recovery Extension

The follow-up persistence work keeps HCM as the normal source of truth while
allowing modules to retain safe local state during an outage.

- HCM initializes or reuses `/var/lib/homecontrol` as a Git repository.
- The automatic sync job runs on a 10-minute interval in the HCM process and
  stages only `config/`, `logs/`, and `recovery-manifest.json`.
- Local commits are created only when approved tracked content changed.
- GitHub is optional. When configured, HCM pushes pending local commits without
  force-push, history rewrite, or automatic pull.
- GitHub credentials are stored outside the repository under `.secrets/` and
  supplied to Git through an askpass helper, not command-line arguments or remotes.
- GitHub connection verifies repository existence, private visibility, and write
  permission through the GitHub API before marking the connection enabled.
- Runtime Git sync status is stored outside tracked configuration under `.state/`.
- Diverged local/remote histories stop remote synchronization and retain local data.

Module configuration synchronization now uses revisioned packages with checksums.
Modules atomically persist accepted packages, reject stale updates, and report
configuration synchronization state in heartbeat/status payloads. Offline local
maintenance lockouts are preserved during reconciliation; stale HCM data cannot
silently clear a locally locked channel. Unlocking remains an explicit authorized
operation.

The module emergency web server exposes:

- `GET /health` without credentials, containing identity, heartbeat, component
  health, sync status, active faults, pending logs, and bounded recent logs.
- `POST /login` and `POST /logout` using module-local administrator credentials.
- `GET /config` for authenticated local administrators.
- `PATCH /config` for authenticated local administrators with CSRF validation.

Offline administrator credentials are provisioned as salted PBKDF2 password
hashes from HCM configuration payloads. No default password is present. Failed
logins are rate-limited, local sessions are bounded, and local actions generate
audit log events queued for HCM delivery.

Module log delivery is separate from Git synchronization. Modules keep writing
local JSONL logs and queue event records while HCM is unreachable. On TCP session
recovery, queued log events are sent through the authenticated module channel;
HCM durably appends deduplicated events under `/var/lib/homecontrol/logs/<module>/`
before acknowledging delivery.

Disaster recovery from Git backup should restore files only. Restored
configuration must be reviewed and synchronized through HCM/module reconciliation;
restoration alone must not energize outputs or replay stale ON commands.

## Not Implemented or Not Physically Verified

- Full CSV-to-module file mirroring for every production RCM/LCM file remains pending.
- Conflict-resolution UI for concurrent non-safety edits remains pending.
- Real LCM analog PWM hardware is intentionally left as `TBD`; the model, address, frequency,
  and polarity remain unverified.
- Real Shelly Pro dimmer control is represented only as disabled network I/O health metadata.
  No RPC contract or physical command path was introduced.
- RCM relay output feedback is not available; state remains commanded-only.
- Real hardware writes from emergency pages remain disabled unless module policy and verified
  adapters explicitly permit them.

## Safety Notes

- Real hardware adapters remain disabled by default.
- Browser and preview paths continue to route commands through authenticated HCM APIs.
- No direct browser-to-module hardware control path was added.
- Maintenance, fire/life-safety, and existing safety arbitration behavior were not weakened.
