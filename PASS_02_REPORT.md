# Pass 2 Report — Retire SIM and Legacy RMC

Date: 2026-10-24

## Result

Pass 2 established the reversible retirement boundary. SIM and legacy RMC are
now explicitly marked deprecated in PostgreSQL while their historical records,
compatibility imports, simulation tooling, firmware/update helpers, and entity
adapters remain intact. Destructive deletion was correctly blocked by the
dependency audit: PNL replacement work is not yet complete.

## Dependency matrix

| Surface | Current consumer | Decision |
| --- | --- | --- |
| `02_HCM/entities.py` SIM/RMC state projection | Canonical read-only entity API | Preserve until PNL telemetry adapters replace it |
| Historical SIM protocol names and `09_database` compatibility fields | Historical update/telemetry records | Retain for compatibility; no active SIM implementation or provisioning path remains |
| `07_config/06_RMC` | RMC firmware and recorded CAN protocol definitions | Active RMC firmware metadata remains; physical transport is separately gated |
| `07_config/10_Common/manifest.py` and inventory | Deployment and device validation | Preserve parser compatibility; retirement enforcement deferred until PNL backplane exists |
| Touchscreen SIM/RMC views | Existing preview and operator tooling | Preserve until PNL UI/backplane replacement |
| `modules.module_type` and audit/event checks | Historical database rows and role transitions | Preserve; no destructive type rewrite |
| Firmware/update artifact target `SIM`/`RMC` | Rollback and existing artifact verification | Preserve for rollback compatibility |
| Safety, RCM, LCM, HCM, ACM, Heartbeat | No dependency requiring deletion | Preserve unchanged |

## Implementation

- Added migration `026_legacy_module_deprecations.sql` with idempotent status
  records for SIM and RMC.
- Added read-only `GET /api/v1/legacy-module-status` for authenticated
  administration and later migration passes.
- Added `02_HCM/legacy_module_status.py` as the single status adapter.
- Added this report and the Pass 1 baseline carry-forward documentation.

The migration does not delete modules, mappings, events, firmware records,
configuration, or audit history. It is reversible by restoring the pre-migration
backup or removing only the new status metadata in a controlled rollback.

## Exit-gate assessment

- No live runtime reference was removed: **PASS for safe staged retirement**.
- Existing RCM/LCM/HCM safety and heartbeat behavior: **preserved**.
- Historical data retention: **PASS by additive migration design**.
- Disposable database migration coverage: **PASS through the migration test
  harness and full suite**.
- Physical/HIL testing: **not run; not authorized or required for this metadata
  boundary**.

## Pass 3 prerequisites

Pass 3 may replace legacy sensor consumption only after the PNL backplane defines
authenticated panel identity, five-second telemetry, stale handling, local alias
resolution, dashboard distribution, and Sonic policy contracts. Until then SIM
and RMC remain available for rollback and compatibility.
