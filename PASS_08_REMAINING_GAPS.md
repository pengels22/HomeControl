# Pass 8 remaining gaps

## Software

- Existing HCM state producers still need a single publication hook to populate
  `pnl_state_events` for every state change.
- The browser editor needs panel/area assignment controls and catalog-backed
  entity picking; its preview remains non-executable.
- Expired telemetry and ledger retention should be scheduled in deployment.

## Live deployment

- Migration 029 has not been applied to the Jetson or any other live host.
- Production TLS/client certificate validation and service restart behavior are
  unverified and require explicit deployment approval.

## SVR1 and physical hardware

- No configured authenticated SVR1 ASR endpoint was available; transcription
  remains a deterministic contract.
- ESP32-P4, W5500, sensors, touchscreen, microphone, speaker, and power rails
  remain hardware gates.

## Legacy retirement

SIM/RMC compatibility code and historical records remain intentionally preserved.
Final retirement requires an inventory proving no deployed consumer remains.
