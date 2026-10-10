# Phase 4 progress: HCM registry foundation

Status: repository implementation only. These changes are not deployed to the
Jetson and the migration has not been applied to the live PostgreSQL database.

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
.venv/bin/python -m pytest
```

The pytest run passed with Python 3.14 deprecation warnings from
`pytest-asyncio`. Those warnings do not indicate HCM test failures.

PostgreSQL integration tests require a disposable test database URL:

```sh
HCM_TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest 11_tests/test_phase4_postgres_integration.py
```

They intentionally skip when `HCM_TEST_DATABASE_URL` is not set. They must not
point at the live Jetson database.

## Deployment note

Do not apply `003_module_registry_foundation.sql`, rebuild the HCM container,
restart services, or deploy dashboard changes to the Jetson without a separate
operator-approved maintenance plan and rollback checklist.
