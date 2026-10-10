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
```

The pytest run passed with Python 3.14 deprecation warnings from
`pytest-asyncio`. Those warnings do not indicate HCM test failures.

## Deployment note

Do not apply `003_module_registry_foundation.sql`, rebuild the HCM container,
restart services, or deploy dashboard changes to the Jetson without a separate
operator-approved maintenance plan and rollback checklist.
