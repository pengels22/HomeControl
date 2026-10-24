# Pass 8 — Production HCM PNL integration

## Delivered

- Added migration 029 for production panel metadata, credential audit, command
  deduplication, occupancy events, bounded state events, and dashboard assignment
  uniqueness.
- Added `01_HCM/pnl_production_api.py` and registered it in `main.py`.
- Added transactional admin registration, area/hostname management, enable/
  revoke, credential rotation, published dashboard assignment and Sonic policy
  administration.
- Added authenticated panel config, conditional dashboard retrieval, entity
  snapshots, bounded event resynchronization, commands, occupancy events,
  heartbeat contact, Sonic policy delivery, and epoch acknowledgements.
- Made telemetry sequence validation atomic under row locking and exposed
  explicit validity flags through the existing API.
- Added focused production API tests and the required Pass 8 reports.

## Architecture decisions

HCM remains the authority for areas, published dashboards, entity permissions,
commands, and microphone policy. PNL local aliases remain panel-scoped. Commands
continue through `command_logical`; no direct RCM/LCM/HVAC path was introduced.
The panel event endpoint is bounded and resynchronizable rather than a second
heartbeat protocol. SVR1 remains a configurable speech service, not an HCM audio
proxy.

## Validation

- Focused production/API/PNL/dashboard tests: 17 passed.
- Full pytest suite: 853 passed, 46 skipped.
- Compileall, JavaScript syntax validation, migration/schema checks, and
  `git diff --check` passed.

No live migration, deployment, physical output, hardware, or network change was
performed. PostgreSQL disposable integration remains pending because the test
database URL is not configured.
