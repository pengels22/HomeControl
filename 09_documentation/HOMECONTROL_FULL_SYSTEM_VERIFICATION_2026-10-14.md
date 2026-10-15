# HomeControl Full System Verification

**Audit date:** 2026-10-14 to 2026-10-15 UTC  
**Repository:** `feature/hardware-integration-config-logging`  
**Audited HCM release:** `83506b21c0420b01817996f6b261e747cf6b37f8`  
**Scope:** Verification only. No deployment, restart, role change, output command, account change, password change, network change, or GitHub change was performed during this audit.

## Executive result

The central HCM service, PostgreSQL service, Conflict heartbeat registry, LAB1 emergency service, and LAB1 simulation/output inhibition were live-verified. The software test suite passed. The audit found two material operational gaps:

1. The deployed HCM image does not contain the `git` executable. The live Settings Git endpoint returns HTTP 500 and the stored Git status contains `Local Git commit failed`.
2. No enabled ten-minute HomeControl Git synchronization service or timer was found. Local configuration synchronization is covered by code and simulation tests, but the complete HCM-to-module and offline-reconciliation workflow is not live-proven.

These gaps mean the system is **not fully verified for production configuration persistence and synchronization**, although they do not indicate an output actuation or safety bypass.

## Verification levels

- **LIVE VERIFIED:** Direct read-only observation of the running service or host.
- **SIMULATION VERIFIED:** Automated tests or LAB1 simulation evidence; not proof of physical hardware behavior.
- **CODE REVIEWED:** Implemented and covered by source/tests, but not proven against the live integration.
- **NOT VERIFIED:** Evidence was unavailable or the required live path was not exercised.
- **FAILED:** The observed live behavior does not meet the intended contract.

## Baseline and releases

| Item | Result |
|---|---|
| Git branch | `feature/hardware-integration-config-logging` |
| Repository state | Clean at audit start; tracking origin without divergence |
| HCM release | `83506b21c0420b01817996f6b261e747cf6b37f8` |
| HCM deployment record | `hc-20261014T203216Z-72cca1d5` |
| HCM rollback container | `hcm-rollback-hc-20261014T203216Z-72cca1d5` |
| LAB1 release marker | `cf783fa7adc40102ea2bc12d922a91d1b827a2ee` |
| LAB1 prior backup | `hc-20261014T194048Z-dedb138f` |
| Conflict release marker | `7a3fcdc9cc9596ab53de531b54f2713a6b850238` |
| HCM host | `192.168.20.27` |
| Conflict host | `192.168.20.26` |
| LAB1 host | `192.168.20.36` |

## Test and static verification

**LIVE VERIFIED / PASS**

- Full suite: `394 passed, 9 skipped, 1028 warnings in 6.82s`.
- The nine skips are the PostgreSQL integration cases in `11_tests/test_phase4_postgres_integration.py`; each requires `HCM_TEST_DATABASE_URL`.
- Python compilation: `python -m compileall -q` over `00_Heartbeat`, `01_HCM`, `02_SIM`, `03_LCM`, `04_RCM`, `05_PNL`, `06_config`, `07_servises`, `08_database`, `10_scripts`, and `11_tests` passed.
- JavaScript syntax: `node --check 01_HCM/www/app.js` passed.
- `git diff --check` passed before this report was added.
- Focused management tests previously run: `25 passed`.

The suite emitted dependency deprecation warnings from Starlette/httpx and pytest-asyncio. No test failure was observed.

## HCM and PostgreSQL

**LIVE VERIFIED**

- `hcm-test` was running image `homecontrol-hcm:83506b21c0420b01817996f6b261e747cf6b37f8`.
- `hcm-postgres` was running PostgreSQL 16.
- HCM health API returned `{"ok":true}` and the remote HCM verification passed.
- HCM, PostgreSQL, HCM heartbeat, and watchdog timer systemd units were active. The watchdog service is an expected completed oneshot; its timer was active and waiting.
- Database connectivity and schema were available. Relevant counts at audit time: `users=1`, `ADMIN users=1`, `modules=1`, `bindings=0`, `active faults=0`, `active safety events=0`, `output arbitration events=0`, `configuration history=0`, and `management events=44`.

**Warnings**

- The live module registry contained one LAB1 module and no logical bindings.
- HCM registry `supervision_state` was `unknown` even though the authenticated control session was online. This is a status-quality warning, not evidence of an output command.
- The database session count was zero at query time; no current live user session was inferred from this value.

## Conflict heartbeat and supervision

**LIVE VERIFIED**

- Conflict status at `192.168.20.26:6004` returned HTTP 200.
- Conflict device ID: `3c53fbb7adb2`.
- Conflict registry showed authorized, online entries for LAB1 and Jetson with recent observations, correct addresses, and no fault.
- Remote verification reported the registry integrity and HMAC heartbeat as healthy; LAB1 heartbeat acknowledgement age was approximately two seconds during the check.
- No heartbeat errors were found in the relevant Conflict journal query.

**Warning**

Conflict's own `peer` field reported `enabled:false`, `online:null`, and `not yet connected`. The independent registry and HMAC heartbeat path was healthy. This distinction should be resolved as a later supervisory-status cleanup; no change was made during the audit.

## LAB1 identity, role, and output safety

**LIVE VERIFIED**

- Permanent device ID: `2ccf675d3414`.
- Current registered and reported role: `SIM`.
- `simulation=true`.
- `physical_outputs_enabled=false`.
- LAB1 host heartbeat and local emergency service were active.
- HCM control session was online; no command or role transition was issued during this audit.
- HCM database showed zero logical bindings and zero output arbitration events.
- LAB1 `/health` identified the expected device, hostname, role, simulation state, and output inhibition.
- Anonymous access to LAB1 `/config` returned HTTP 401 with local administrator authentication required.

**SIMULATION VERIFIED / NOT PHYSICAL VERIFIED**

The available evidence establishes the current simulation-only state and output inhibition. No physical RCM/LCM hardware was present for live electrical verification; physical output behavior remains **NOT VERIFIED**. There is no evidence from this audit of an unexpected output command.

LAB1 local health reported `hcm_heartbeat_health.connected=false` from the emergency server's local view. The independent host HMAC heartbeat service and Conflict registry were healthy; these are separate paths and should not be conflated.

## Emergency UI

**LIVE VERIFIED**

- LAB1 port 6010 was active.
- HCM's authenticated settings data reported:
  - `available=true`
  - `status=available`
  - URL `http://192.168.20.36:6010`
  - reason `Verified module-advertised emergency service`
- The service health identity matched the registered module ID.
- The local emergency page required administrator sign-in; no unauthenticated configuration access was granted.
- An earlier authenticated browser verification in this release family displayed `Open Configuration`; following the service endpoint reached the local authentication page. The current audit revalidated the live API response and endpoint health without changing configuration.

## Module registry and role reconciliation

**LIVE VERIFIED**

The live registry kept the permanent hardware identity separate from module type and operational role. LAB1 was registered as and reported `SIM`, with the latest recorded role transition to SIM confirmed before this audit. No startup or heartbeat-based role mutation was observed or initiated.

The current registry state is internally consistent. The stale LCM-shaped local CSV described below is a configuration-sync warning, not evidence that HCM should change LAB1's role automatically.

## Configuration persistence and synchronization

**SIMULATION VERIFIED / CODE REVIEWED; LIVE END-TO-END NOT VERIFIED**

- Tests cover RCM 32-channel and LCM 22-channel CSV schemas, atomic writes, revisions/checksums, stale-update rejection, lockout preservation, and conflict handling.
- LAB1 had a local LCM CSV with 22 channels and metadata revision `375eb23b554d7fc2af9af0bb301a8b73867f275c9ebf6388db9c1a21fa76fd4e` as observed on the device. Its metadata state was `local_changes_pending_hcm_reconciliation`, with a local edit at `2026-10-14T19:07:55Z` and one pending log event.
- HCM's live `configuration_history` count was zero and its mounted HCM `config/` tree contained directories but no configuration files.
- The active LAB1 role was SIM while the local CSV was LCM-shaped. This is a stale/pending local configuration condition and must be reconciled through an authorized workflow later; it was not altered during the audit.
- No complete HCM-to-module acknowledgement and offline reverse-reconciliation cycle was proven against live persistence.

## Git storage and synchronization

**FAILED LIVE**

- HCM persistent storage was mounted at `/srv/hcm-data/homecontrol` on ext4 and contained `.git`, `.state`, `.secrets`, `config`, `logs`, and `recovery-manifest.json`.
- The HCM container had no `git` executable. The live Settings Git endpoint `/api/v1/settings/git` returned HTTP 500 with `FileNotFoundError: [Errno 2] No such file or directory: 'git'`.
- `.state/git-status.json` recorded `last_error: Local Git commit failed`.
- No enabled HomeControl Git synchronization service or timer was found in the host systemd inventory.
- The host-side repository could not be inspected with Git because Git's dubious-ownership safety check rejected the path. No Git configuration was changed.

This is a confirmed operational defect. It was not repaired because the requested workflow was verification-only.

## Logging and recovery

**CODE REVIEWED / SIMULATION VERIFIED; LIVE CENTRAL ARCHIVAL NOT VERIFIED**

- Tests cover structured logging, offline queueing, reconnect handling, and deduplication.
- LAB1 had one local event in `events.jsonl` and one pending event queue.
- HCM's mounted `logs/HCM` directory was empty at inspection time, and the recovery manifest had empty archived-log timestamps and no logical module identifiers.
- No log repair, queue flush, or persistence mutation was performed.

## Authentication, users, and authorization

**CODE REVIEWED / PARTIAL LIVE VERIFIED**

- HCM database contained one ADMIN user and no plaintext password fields were exposed by the audit.
- LAB1's local authentication metadata was protected (`600`), contained one ADMIN role, and exposed no password fields.
- Anonymous LAB1 configuration access was rejected with HTTP 401.
- Automated coverage includes central user snapshots, authentication, CSRF, offline authentication, session expiry, throttling, and ADMIN/READONLY authorization behavior.
- A current live credential login was not repeated during this verification run; prior browser authentication was observed during the preceding deployment workflow. Current live password authentication is therefore **NOT VERIFIED** in this audit.

## Network and Settings UI

**LIVE VERIFIED**

The authenticated HCM Settings network data came from the configured host-status provider and reported actual Jetson interfaces, including:

- `eth0`: IPv4 `192.168.20.27/24`, link up, default gateway `192.168.20.1`, metric 100.
- `wlan0`: IPv4 `192.168.20.25/24`, link up, default gateway `192.168.20.1`, metric 20600.
- Loopback, Docker, bridge/veth, dummy, and Tailscale interfaces were also reported by the provider.
- IPv6 link-local addresses were present where configured.

The provider source was `configured_host_status_file`; no interface configuration was changed. The UI/API correctly distinguished available host data from the earlier unavailable state.

The live frontend was previously authenticated and visually checked in this release family for the Settings network data and emergency link. The current API response was rechecked during this audit. No current browser credential session was assumed after service restart.

## Physical and peripheral integration

**NOT VERIFIED / SIMULATION VERIFIED**

- No live RCM, LCM, PNL, Shelly, I2C, CAN, or physical output hardware was exercised.
- Simulator and protocol paths are covered by automated tests.
- No physical GPIO or production TLS claim is made by this report.
- Fire/life-safety and maintenance-lock code paths are covered by tests, but physical fail-action behavior was not electrically tested.

## Safety and change control

**LIVE VERIFIED for non-actuation evidence**

- No output command, role transition, binding change, account change, password change, service restart, or network mutation was initiated during this audit.
- LAB1 remained simulation-only with physical outputs disabled.
- HCM reported zero output arbitration events and zero logical bindings at inspection time.
- Conflict and LAB1 were not deployed to or modified.

Physical actuation safety remains **NOT VERIFIED** because no physical hardware was available for an electrical test.

## Prioritized corrective work

1. **P0:** Provide the HCM image with a pinned, supported `git` executable or replace the Git provider with a tested equivalent. Add a live health check for `/api/v1/settings/git`.
2. **P0:** Restore and verify the intended periodic HCM configuration synchronization service/timer, including durable failure reporting and rollback-safe reconciliation.
3. **P1:** Reconcile LAB1's pending local configuration through the authorized HCM/role-aware workflow. Do not infer or mutate its role from the stale CSV.
4. **P1:** Run PostgreSQL integration tests with an isolated `HCM_TEST_DATABASE_URL` and retain the results with the release evidence.
5. **P2:** Clarify Conflict's disabled self-peer status versus its healthy HCM/LAB1 registry supervision.
6. **P2:** Establish live central log archival/recovery evidence and verify watchdog notification/rate-limit behavior; those claims were not validated here.
7. **P2:** Perform a separately authorized physical-output and peripheral integration test with explicit safety controls.

## Final disposition

**Audit result: PARTIAL PASS; production configuration persistence and synchronization remain blocked.**

The core HCM service, database, Conflict heartbeat registry, LAB1 identity, LAB1 simulation/output inhibition, emergency UI validation, and host network reporting were verified without changing production state. The missing Git executable, absent synchronization timer, pending LAB1 local reconciliation, and unverified physical/persistence paths must be resolved and re-audited before claiming full system integration.
