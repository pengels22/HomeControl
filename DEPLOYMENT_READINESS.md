# HCM Phase G Deployment Readiness

Audit date: 2026-10-23 16:21 UTC
Recommendation: **NO-GO for live deployment**

## Candidate

- Candidate commit: `5f1228e655a8b1583bccfcb583620157d5faa312`
- Candidate image tag: `homecontrol-hcm:5f1228e655a8b1583bccfcb583620157d5faa312`
- Candidate source tree was clean before this readiness record was added.
- The candidate image was built on the target-compatible Jetson ARM64 Docker environment and passed the image SHA verification step.

The software candidate is the verified Matter-centric rebuild through Phase F. This pass records deployment evidence and gates; it does not apply migrations, build a live image, or change a deployed host.

## Evidence status

| Gate | Status | Evidence or required action |
|---|---|---|
| Source commit | PASS | Full candidate SHA recorded above; current branch was clean at audit start. |
| Python, JavaScript, Matter, and repository checks | PASS | `873 passed, 1 skipped`; Python compileall passed; both JavaScript syntax checks and Matter `npm run check` passed; Matter validate-only exited 0; `git diff --check` passed. |
| Docker image build | PASS | Built on Jetson ARM64 as `homecontrol-hcm:5f1228e655a8b1583bccfcb583620157d5faa312`; image ID `sha256:7a390d24dbac6de440a54ffad493efc3ccee019c3b06148d0cf5a8f22885ea78`, 495,772,700 bytes. |
| Jetson inventory | PASS | Host `jetson`, Ubuntu 18.04.6, kernel `4.9.253-tegra`, arm64, uptime 12 days 23 hours at collection. No extra active HCM container was found. |
| Current/rollback image | PASS | Running `hcm-test` is `homecontrol-hcm:b1ef32db2ac870278f93a8371308818df9a4f379`; rollback is `homecontrol-hcm:bd549fe15ca70f30346336d00ed42883f25bbf9f` in `hcm-rollback-hc-20261022T234445Z-cd2e59bc`. |
| Database migration level | PASS | Live `homecontrol` is at migration 024; migration 025 is pending. Database size is 12 MB. |
| Database backup and restore test | PASS | `/srv/hcm-data/backups/homecontrol-20261023T161520Z-migration024.dump`, custom format, 239,240 bytes, SHA-256 `f730f34de929bf615dd18825eb844074e2ca05694c5487fecf03a4b156047018`; `pg_restore --list` succeeded and isolated PostgreSQL restore succeeded. |
| Clone migration 025 | PASS | Candidate migration runner applied `[25]` to the restored clone. `hcm_areas` and `rooms.area_id` were present; sampled Rooms, users, modules, channel metadata, logical devices, and Matter endpoint tables survived. |
| Matter storage backup | BLOCKED | Running container has no `HCM_MATTER_STORAGE`, no Matter bridge process, and no Matter storage path under `/srv/hcm-data` or `/etc/hcm`. There is no live Matter state to back up, but this is a deployment blocker for the Matter-centric candidate. |
| Application/config backup | PASS | `/srv/hcm-data/backups/hcm-config-20261023T161638Z.tar.gz`, 2,628 bytes, mode 600, SHA-256 `1746817c2003a32f5876d7c9f451fc91418bc23c61ea21c75ade0cb1e914397f`; contains non-secret HCM config/state, service unit, safety config, release marker, and redacted container inventory. |
| Disk capacity | PASS WITH RISK | Jetson root has 4.9 GiB free of 14 GiB (63% used); `/srv/hcm-data` has 14 GiB free of 15 GiB (1% used). Docker reports 1.772 GB images, 477 kB containers, 151.1 MB unused volumes, and no build cache. Nothing was pruned. |
| Hardware/HIL | NOT RUN | GPIO, physical relays, TLS on deployed modules, and production hardware behavior remain unverified and require an authorized HIL window. |
| Candidate validate-only start | DEFERRED | The image's build-time `hcm_verify` passed and migration runner was exercised against the clone. A full app container start was deferred to avoid introducing another listener/configuration while the live deployment remains active. |
| Rollback compatibility | NOT PROVEN | The 024 backup restored and 025 clone migration passed, but the old rollback image has not been run against a migrated clone. Until that test is approved, rollback after migration requires restoring the 024 database backup. |

## Migration and rollback assessment

The repository contains ordered migrations 001 through 025; 025 creates `hcm_areas` and adds nullable `rooms.area_id`. No live migration was applied during this audit. Although this change is additive, compatibility with the installed Jetson schema and an older image has not been proven on a restored clone. Treat rollback as an image rollback **plus restoration of the pre-migration database backup** until that compatibility test passes.

`11_scripts/hcm_docker_deploy.py` validates a full expected SHA, preserves the configured networks and storage bind, health-checks the replacement, and attempts recovery of the original container on failure. It does not create database, Matter-storage, or configuration backups, and it does not build the image. Those steps are mandatory external preflight gates.

## Required pre-deployment sequence

1. On the approved Jetson maintenance window, capture read-only inventory: running HCM container/image digest, rollback container, enabled HCM units, network attachments, `/srv/hcm-data` capacity, migration table, Matter storage path, and configuration paths. Do not expose credentials in the record.
2. Create and verify a PostgreSQL dump, checksum it, and restore it into an isolated PostgreSQL instance. Confirm the restored schema and application checks before touching the live database.
3. Back up the complete Matter storage directory and application/configuration bind. Confirm that the backup contains the existing fabric and endpoint state; never regenerate this state as a substitute.
4. Build and inspect `homecontrol-hcm:639ca1616291d0dc17923438e94a9e2d90d2fa69`, record its immutable digest, and verify the expected SHA in the image metadata.
5. Apply migration 025 only after the installed level and backup evidence are recorded. Keep the prior image and named rollback container available.
6. Deploy with the existing helper, using the exact 40-character expected SHA. Monitor health and logs, then execute the acceptance checklist below.

## Acceptance checklist

- [ ] HCM health endpoint and authenticated API respond.
- [ ] PostgreSQL connectivity and migration state are healthy.
- [ ] RCM, LCM, SIM, and PNL persistent TLS connections reconnect and report heartbeats.
- [ ] Logical devices, Areas, Rooms, and Matter endpoint mappings load without identity changes.
- [ ] Matter bridge starts against the preserved storage and retains fabric/endpoint identity.
- [ ] Native Time Service is available; native NWS Weather works or reports its documented degraded state.
- [ ] Safety and maintenance-lockout priorities, fire handling, and output fail behavior pass the approved checks.
- [ ] Diagnostics expose no secret material and report the expected candidate SHA.
- [ ] Authorized HIL verifies physical inputs, outputs, relays, and reconnect behavior.

## Rollback procedure

1. Stop only the candidate HCM container/service and preserve its logs.
2. Confirm the recorded rollback container and prior image digest; invoke `hcm_docker_deploy.py rollback` with that exact rollback identity.
3. If migration 025 was applied and compatibility was not proven, restore the verified pre-migration PostgreSQL backup before starting the old image.
4. Restore Matter/configuration storage only from the verified backup if corruption or an identity mismatch is observed; do not recreate fabric state.
5. Verify health, module heartbeats, logical-device mappings, safety behavior, and the acceptance checks before reopening control.

## Phase H live findings

- Current HCM API reports commit `b1ef32db2ac870278f93a8371308818df9a4f379` and health `ok: true`.
- The current HCM service is an active-exited oneshot that starts `hcm-test`; PostgreSQL and host Heartbeat V3 are running independently.
- The live container uses the expected `hcm-control` and `hcm-internal` networks, binds `/srv/hcm-data/homecontrol` to `/var/lib/homecontrol`, and publishes only the expected HCM ports on `192.168.20.27`.
- A failed short-tag build left one inactive Docker build container named `elastic_lovelace`; it is not an active HCM container and was intentionally not removed during this no-cleanup phase.
- Matter is not configured in the current deployment. The candidate cannot receive a GO decision until an approved persistent Matter storage path and backup/restore plan exist, or the deployment architecture is explicitly re-baselined to omit Matter.

Until the Matter persistence blocker is resolved and authorized HIL/acceptance checks are complete, the candidate is not ready for live rollout.
