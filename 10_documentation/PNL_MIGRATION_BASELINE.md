# PNL Migration Baseline

Date: 2026-10-24
Repository: `pengels22/HomeControl`
Pass: 1 of 6

## Source state

- Baseline commit before Pass 1: `91ee92dfb5790b651b7f8a5123dd3f513233c400`.
- Branch: `main`, aligned with `origin/main` at audit start.
- Worktree: clean at audit start; no user changes were overwritten.
- The attached six-pass plan is treated as project direction. It does not by
  itself authorize live host changes, hardware energization, or commissioning.

## Current architecture inventory

| Boundary | Current authority | Pass 1 decision |
| --- | --- | --- |
| HCM control and safety | `01_HCM`, shared arbitration, module registry | Preserve. No safety or output path changes. |
| PostgreSQL configuration | Existing schema and ordered migrations through 025 | Preserve. Migration 025 is additive and remains deliberate. |
| Rooms and HCM Areas | `rooms`, `hcm_areas`, nullable `rooms.area_id` | Preserve as the location model for PNL work. ACM Areas remain separate. |
| Canonical entities | `01_HCM/entities.py` over channel/module state | Preserve as the only physical entity projection. Extend through adapters. |
| Matter | `01_HCM/bridges.py` plus Matter.js child and persistent storage | Preserve endpoint allocation and host-backed SDK storage. No commissioning claim. |
| Time and NWS | Native `time_service.py` and `weather_service.py` | Preserve. Fixed NWS coordinate/cache recovery defect in Pass 1. |
| Consumer integrations | Compatibility source/API paths; inactive during normal startup | Do not delete until dependency review proves safe. |
| PNL | Existing Python module surface | No firmware implementation in Pass 1. |
| SIM/RMC | Existing legacy module and CAN surfaces | No deletion in Pass 1. Dependency audit is required first. |
| Heartbeat/Conflict/ACM | Independent deployed services and firmware | Preserve Ethernet-first VLAN 20 and existing protocol boundaries. |

## Reconciled documentation findings

The architecture audit records completed Checkpoints 1–7: HCM Areas, canonical
entity projection, Matter mapping/lifecycle, native Time, native NWS, admin UI
refocus, and staged legacy-provider retirement. The implementation and tests in
the current tree match those checkpoints. They establish a usable HCM boundary
for later PNL work, but do not constitute PNL firmware, hardware commissioning,
or removal of SIM/RMC.

The attached plan's Pass 1 request to finish the current HCM work therefore has
one concrete software defect to resolve before proceeding: NWS rejects overly
precise point coordinates with a redirect, while the bounded HTTP client does
not follow redirects. An incomplete cached point record could also block future
recovery. Pass 1 canonicalizes coordinates to the NWS-supported precision and
retries incomplete cached point metadata.

## Carry-forward decisions

1. Keep HCM as the sole control authority and retain all safety, reconciliation,
   module identity, Heartbeat V3, ACM, and deployment boundaries.
2. Use PostgreSQL `hcm_areas`, `rooms.area_id`, and canonical entities for PNL
   identity and authorization; do not create a second room or area database.
3. Treat `local.*` as panel-scoped aliases in the future PNL backplane, mapped to
   globally unique authenticated panel sensor identities.
4. Audit SIM/RMC callers and historical data before any retirement migration.
5. Keep Matter endpoint tombstones and persistent storage; defer real controller
   commissioning and HIL claims.
6. Treat NWS as degraded when upstream data is unavailable and retain explicit
   health/cache state rather than inventing values.

## Known risks

- Physical GPIO, relay, CAN, module TLS, Matter controller interoperability,
  mDNS/IPv6, and PNL hardware remain unverified.
- Existing provider runtime still supplies core automation, event, zone,
  notification, and native primitive dependencies; broad deletion is unsafe.
- The installed Jetson database has already received migration 025 during the
  separately authorized deployment window. Future source changes still require
  backup, clone testing, and deliberate migration review.
- The current source tree does not contain ESP32-P4 firmware for the proposed
  Waveshare panel.
