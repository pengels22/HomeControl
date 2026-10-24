# Pass 3 Report — HCM PNL Backplane

Date: 2026-10-24

## Result

Pass 3 establishes the software backplane contract for PNL identity, telemetry,
panel-scoped local aliases, stale handling, and Sonic's fail-muted policy
storage. The implementation is simulator/software-only. No ESP32 firmware,
GPIO, sensor, audio, or physical network claim is made.

## Implemented contract

- Migration `027_pnl_backplane.sql` adds `pnl_devices`, append-only
  `pnl_telemetry_events`, and singleton `sonic_policy` records.
- `02_HCM/pnl_backplane.py` validates authenticated panel identity, monotonic
  sequence, timezone-aware timestamps, bounded sensor values, and required
  `local.lux`, `local.occupancy`, `local.temp`, `local.humidity` fields.
- `POST /api/v1/pnl/telemetry` accepts only a registered enabled panel with a
  bearer token whose SHA-256 hash is stored in the registry. Spoofed identity,
  replayed sequence, stale/future timestamps, malformed values, and out-of-range
  readings are rejected.
- Local aliases are scoped as `pnl_<panel-id>_local_*`; identical aliases from
  two panels cannot collide. Telemetry is marked stale after 15 seconds by the
  panel inspection API, independently of Heartbeat V3.
- `GET /api/v1/pnl/devices` and `/devices/{id}/aliases` provide authenticated
  inspection for administration and future dashboard compilation.
- The existing HCM authority remains the only command path. This pass adds no
  direct PNL-to-module control path.

## Deferred by design

Dashboard schema/distribution, dynamic area entity selection, command ACK
contracts, audio session transport, and browser editing are implemented in
later passes. The native PNL firmware, LVGL renderer, sensor drivers, and
physical Heartbeat client remain Pass 4 work.

## Validation

Focused PNL and migration tests pass. The full suite, compileall, JavaScript
syntax, migration/configuration checks, and diff checks are required before the
Pass 3 commit is finalized.

## Pass 4 prerequisites

Pass 4 must consume this API contract, retain panel identity and local alias
semantics, and implement a simulator before any board-specific driver is
described as working. Hardware wiring remains a bench-test gate.
