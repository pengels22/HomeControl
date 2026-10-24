# Pass 7 — PNL end-to-end integration and gap closure

## Implemented

- Added `05_PNL/simulation.py`, a deterministic in-memory HCM/PNL/SVR1 contract
  covering three panels, area assignment, shared dashboard distribution,
  panel-local aliases, telemetry, occupancy events, Unified Heartbeat V3,
  freshness separation, HCM-authoritative commands, duplicate protection,
  reconnect behavior, and global Sonic mute/session handling.
- Extended telemetry validation with explicit per-sensor validity and bounded
  temperature values; exposed the 15-second freshness constant and validity in
  local alias responses.
- Added the complete Pass 7 audit, integration evidence, hardware blockers, and
  SIM/RMC retirement assessment reports.

## Tests and quality gates

- Focused Pass 7 integration/backplane tests: 11 passed.
- The deterministic fixture covers all five approved card types and negative
  cases for unauthorized identity, replay, duplicate commands, invalid layout,
  stale telemetry, unavailable HCM, and muted voice sessions.
- No live deployment, hardware test, network change, or credential change was
  performed.

## Limitations

The persistent registration/assignment workflow still requires a production
admin API and database integration beyond this software simulator. Physical
ESP32-P4, W5500, sensors, audio, touchscreen, and configured ASR remain blocked
until hardware or an approved SVR1 service is available.
