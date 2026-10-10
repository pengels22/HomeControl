# Phase 4 progress: HCM registry foundation

## Deployment and validation addendum — 2026-10-10 (supersedes pre-deployment status below)

**Status: Phase 4 registry foundation deployed to the Jetson Xavier NX development HCM and smoke-tested.** Git checkout `e19a4a5` (`Finalize Phase 4 registry hardening`) was verified on the Mac and Jetson. This is **not** certification of production readiness or physical module commissioning. Statements below about Phase 4 not being deployed, migrations not being applied, and PostgreSQL tests being skipped describe the earlier pre-deployment state.

### Confirmed development and database validation

- On macOS, PostgreSQL 16.15 ran locally on `127.0.0.1:5433`; a logical `pg_dump` of the Jetson `homecontrol` database was restored into separate `hcm_phase4_clone` and `hcm_phase4_tests` databases.
- The restored clone initially contained zero modules, logical devices and bindings; neither Phase 4 management table existed. The read-only migration `004` preflight returned **0 conflicts**.
- Migrations `003_module_registry_foundation.sql` and `004_phase4_registry_hardening.sql` completed on the clone, and both new tables were confirmed.
- All seven gated real-PostgreSQL integration tests **passed (7/7, none skipped)** on the separate disposable test database; the complete checkout test suite **passed 154/154, zero failed and zero skipped** against commit `e19a4a5`. The full run reported 820 nonfatal warnings, primarily Python 3.14 / pytest-asyncio deprecations.
- These tests exercise migration repeatability, audit rollback, active-binding conflicts including concurrent and NULL-channel cases, room-clearing and logical-device identity preservation across module replacement.

### Live Jetson deployment and verified smoke tests

- Before migration the running Phase 3 application returned dashboard HTTP 200; `hcm.service`, `hcm-postgres.service`, `hcm-heartbeat.service` and `hcm-watchdog.timer` were all active.
- Phase 3 Docker container inspection was saved at `/home/jetson/hcm-phase3-container-backup.json` (sensitive configuration reference). A timestamped, restricted PostgreSQL custom dump was saved as `/home/jetson/hcm-phase4-deployment-20261010-144428.dump` and its archive contents were successfully read through `pg_restore` inside `hcm-postgres`. A backup archive was verified; an end-to-end restore from that specific deployment backup was **not** reported.
- The live database initially matched the clone (0 modules, 0 logical devices, 0 bindings, Phase 4 tables absent). Read-only migration preflight reported **0 conflicts**. Migrations `003` and `004` were applied; `module_capabilities` and `device_management_events` exist, and both `idx_device_bindings_active_channel_unique` and `idx_device_bindings_active_null_channel_unique` were inspected and verified.
- The Jetson repository was fast-forwarded from `5562d62` to `e19a4a5`, clean working tree. Image `homecontrol-hcm:phase4` (image prefix `6846c81e5ace`) was built while `homecontrol-hcm:phase3` (`57ca5785ab2d`) continued running. Additional `phase3-backup` image (`c2e4d768eb82`) was retained. The previous Phase 3 container was designated for preservation as `hcm-phase3-rollback`; its continued presence was not independently rechecked at the end.
- Phase 4 `hcm-test` ran under systemd with the unchanged published dashboard address `192.168.20.27:8080`, Docker networks `hcm-control` and `hcm-internal`, container user `10001:10001`, restart policy `no` and root-only `/etc/hcm/hcm.env`. No application bind mounts were present. No PostgreSQL container or storage relocation was performed.
- After startup settling, the dashboard returned **HTTP 200**, `/api/v1/health` returned **`{"ok":true}`**, and logs showed successful Uvicorn startup with no exceptions in the inspected tail. An initial `HTTP 000` during startup was transient; it subsequently resolved to HTTP 200.
- A direct `asyncpg` connection from the running Phase 4 container to the live `homecontrol` database succeeded; both Phase 4 management tables were queryable with 0 rows, as expected before commissioning.
- OpenAPI returned HTTP 200 and advertised the module, logical-device and binding management routes. Unauthenticated GET requests to `/api/v1/modules`, `/api/v1/logical-devices` and `/api/v1/device-bindings` each returned **HTTP 401**. Subsequently, the user verified **HTTP 200 on all three** from the authenticated dashboard session; the Devices, Logical Devices and Bindings views rendered empty, as expected.
- HCM, PostgreSQL and independent host Heartbeat V3 systemd services were all **active** after switchover; `hcm-watchdog.timer` was **active and scheduled**. Heartbeat's end-to-end status on the Conflict Manager and a post-Phase-4 watchdog fault-injection test were **not** performed in this session.

### Operational boundaries and remaining validation

- Live Jetson/Conflict addresses stay on **VLAN 20**. Jetson `eth0=192.168.20.27` preferred, `wlan0=192.168.20.25`; Conflict USB Ethernet `192.168.20.26`, Wi-Fi `192.168.20.24`. No VLAN 40/60 migration, networking, routing, firewall, Heartbeat V3, systemd/watchdog design or PostgreSQL storage changes were part of Phase 4 deployment.
- Registry and logical-device management deployment is validated; **no physical module was commissioned and no live physical-output actuation was tested**. Management writes were covered in automated tests, not exercised against live hardware.
- Do not mistake API HTTP 200 or a timer being active for end-to-end physical or life-safety validation. Production hardening, HTTPS/credential protection, durable restore testing, PostgreSQL/USB failure supervision, watchdog suppression/notifications and physical commissioning remain separate tasks.
- Retain the Phase 3 image and rollback container (verify actual name/presence before use), the saved Docker inspection, and the PostgreSQL deployment backup until a rollback window is explicitly closed. Because live schema is now migrated, application rollback compatibility should be checked before reverting; do not automatically reverse migrations.
- `docker-compose.yml` is development-only and **must not** be used to reproduce this Jetson deployment (it publishes PostgreSQL and contains development credentials).

---

Historical pre-deployment status: repository implementation only; not yet deployed at the time this section was written. See the deployment addendum above for the current state.

## Implemented in this repository update

- Added additive migration `08_database/003_module_registry_foundation.sql`.
- Added normalized `module_capabilities` persistence separate from module
  configuration, operational state and health.
- Added `device_management_events` for auditable HCM management changes.
- Updated `08_database/schema.sql` so new development databases include the
  Phase 4 registry-foundation tables.
- Extended HCM module registration to persist reported capabilities and
  `control_session_online` state without changing commissioning behavior.
- Added HCM management helpers for module inventory, logical devices and
  physical bindings.
- Added authenticated API routes for module visibility plus ADMIN-only logical
  device and binding writes.
- Extended the HCM dashboard with Devices, Logical Devices and Bindings views.

## Review hardening update

Following independent review of commit `5e8862d`, the repository was hardened
before Jetson deployment:

- Management mutations now run in PostgreSQL transactions with their audit event
  inserts. If audit logging fails, the configuration mutation rolls back.
- Added `08_database/004_phase4_registry_hardening.sql` with partial unique
  indexes that close PostgreSQL `NULL` uniqueness gaps and prevent conflicting
  active physical assignments.
- Binding writes validate module type, declared capabilities and supported
  channel labels before inserting or updating configuration.
- Logical-device room assignment updates distinguish omitted fields from
  explicit `null`, so room assignments can be cleared deliberately.
- Module capability reports are additive by default; replacement/deletion occurs
  only when the module explicitly marks the report as a full snapshot.
- Module registration rejects conflicting `device_id` / legacy `module_uuid`
  mappings.
- Registry connection cleanup is ownership-aware, so an old disconnect cannot
  remove a newer connection or mark the module offline.
- Added PostgreSQL integration tests gated by `HCM_TEST_DATABASE_URL`; they
  apply migrations in an isolated schema and cover migration idempotency,
  rollback on audit failure, duplicate binding rejection and unique-index
  concurrency protection.

## Final hardening update

The final pre-deployment hardening pass tightened the remaining module session
ordering and deployment-review checks:

- Registry activation and disconnect cleanup now use a per-device session lock.
  The active-connection map update and matching online/offline database write
  are serialized for each device identity, so a stale disconnect cannot write
  offline after a replacement connection has become active.
- Added deterministic registry coverage for the reconnect interleaving without
  time-based sleeps.
- Added `08_database/004_phase4_registry_hardening_preflight.sql`, a read-only
  query that identifies existing active binding rows that would violate
  migration `004` partial unique indexes before a deployment window.
- Expanded gated PostgreSQL integration tests for explicit room assignment
  clearing, `NULL` channel binding conflicts, and module replacement preserving
  logical-device identity.

## Boundaries preserved

- No Heartbeat V3 changes.
- No Docker, systemd, watchdog, routing, firewall, VLAN, DHCP or PostgreSQL
  storage changes.
- No live database migration was run.
- No physical module command path is called by registry, logical-device or
  binding management writes.
- Logical devices remain independent from physical module identity. Bindings
  attach logical devices to current module channels, so a future module
  replacement can update bindings without renaming automations or user-facing
  logical devices.

## Tests run locally

```sh
.venv/bin/python -m py_compile 01_HCM/management.py 01_HCM/api.py 01_HCM/models.py 01_HCM/registry.py
.venv/bin/python -m pytest 11_tests/test_registry.py 11_tests/test_management_api.py 11_tests/test_api.py 11_tests/test_identity.py
.venv/bin/python -m pytest 11_tests/test_phase4_postgres_integration.py
.venv/bin/python -m pytest
```

Latest local results:

- `py_compile`: passed.
- Focused registry/management/API/identity tests: `38 passed`.
- PostgreSQL integration file without `HCM_TEST_DATABASE_URL`: `7 skipped`.
- Full pytest: `147 passed, 7 skipped`.

The pytest runs emitted Python 3.14 deprecation warnings from `pytest-asyncio`.
Those warnings do not indicate HCM test failures.

PostgreSQL integration tests require a disposable test database URL:

```sh
HCM_TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest 11_tests/test_phase4_postgres_integration.py
```

They intentionally skip when `HCM_TEST_DATABASE_URL` is not set. They must not
point at the live Jetson database.

No local PostgreSQL server, `initdb`, `psql`, or Docker runtime was available on
the development machine during this pass, so the real PostgreSQL integration
tests were not executed against a disposable server here.

## Deployment note

Do not apply `003_module_registry_foundation.sql`, rebuild the HCM container,
restart services, or deploy dashboard changes to the Jetson without a separate
operator-approved maintenance plan and rollback checklist.
