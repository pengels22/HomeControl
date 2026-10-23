# HCM Phase G Deployment Readiness

Audit date: 2026-10-23 15:25 UTC  
Recommendation: **NO-GO for live deployment**

## Candidate

- Candidate commit: `639ca1616291d0dc17923438e94a9e2d90d2fa69`
- Intended image tag: `homecontrol-hcm:639ca1616291d0dc17923438e94a9e2d90d2fa69`
- Candidate source tree was clean before this readiness record was added.
- Docker is not installed in this audit environment, so the image was not built or inspected here.

The software candidate is the verified Matter-centric rebuild through Phase F. This pass records deployment evidence and gates; it does not apply migrations, build a live image, or change a deployed host.

## Evidence status

| Gate | Status | Evidence or required action |
|---|---|---|
| Source commit | PASS | Full candidate SHA recorded above; current branch was clean at audit start. |
| Python, JavaScript, Matter, and repository checks | PASS | `873 passed, 1 skipped`; Python compileall passed; both JavaScript syntax checks and Matter `npm run check` passed; Matter validate-only exited 0; `git diff --check` passed. |
| Docker image build | NOT RUN | Docker is unavailable locally. Build the exact image tag on the approved build host and record the digest. |
| Jetson inventory | NOT VERIFIED | No Jetson connection was available. Before deployment capture `docker ps`, image/container IDs, systemd state, and filesystem capacity. |
| Current/rollback image | NOT VERIFIED | Record the running image digest, container name, and rollback container identity before stopping anything. |
| Database migration level | NOT VERIFIED | Repository latest is migration 025. Query the live `homecontrol_schema_migrations` table and list pending migrations before applying any change. |
| Database backup and restore test | NOT DONE | Take and checksum a verified `pg_dump` before migration; restore it to an isolated PostgreSQL clone and run schema/application checks. |
| Matter storage backup | NOT DONE | Back up the live `HCM_MATTER_STORAGE` directory before deployment. Its Jetson path was not locally verified. Preserve endpoint identity and fabric state. |
| Application/config backup | NOT DONE | Inventory and back up the live `/srv/hcm-data/homecontrol` bind and deployment environment before mutation. |
| Disk capacity | LOCAL ONLY | Local root has about 70 GiB free (15% used); `/srv/hcm-data` is absent locally. Jetson capacity remains unverified. |
| Hardware/HIL | NOT RUN | GPIO, physical relays, TLS on deployed modules, and production hardware behavior remain unverified and require an authorized HIL window. |

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

Until the Jetson inventory, image build, database restore test, Matter/configuration backups, and authorized HIL are complete, the candidate is not ready for live rollout.
