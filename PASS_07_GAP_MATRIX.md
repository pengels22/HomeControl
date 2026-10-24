# Pass 7 gap matrix

| Requirement | Status | Evidence / correction |
|---|---|---|
| Canonical panel identity and multiple registration | IMPLEMENTED (simulation); PARTIAL (database admin workflow) | `05_PNL/simulation.py` normalizes designated MACs, rejects duplicates, and registers three panels. `pnl_devices` is the persistent target; a production registration UI remains outside this pass. |
| Existing HCM area registry | IMPLEMENTED (simulation contract) | Panels use the three HCM area names and reassignment does not alter dashboard definitions. |
| Authenticated panel session | IMPLEMENTED (simulation); PARTIAL (live API) | Simulator rejects unregistered panels; `/api/v1/pnl/telemetry` verifies bearer token and panel identity. |
| Five-second telemetry and local aliases | IMPLEMENTED | Simulator emits sequenced telemetry; `pnl_backplane.py` validates `local.*`, validity, ranges, replay, and 15-second freshness. |
| Immediate occupancy event | IMPLEMENTED (simulation) | `SimulatedHCM.ingest_occupancy` deduplicates changes independently of telemetry. |
| Unified Heartbeat V3 | IMPLEMENTED | Simulator emits `hcm-heartbeat-v3`, version 3; it does not replace `00_Heartbeat`. |
| Independent telemetry/heartbeat freshness | IMPLEMENTED | `panel_status` tracks each channel separately and has regression coverage. |
| Dashboard distribution and last-known-good | IMPLEMENTED (simulation); PARTIAL (persistent assignment API) | Shared compiled layout is selected by area and refreshed after publish; panel retains its prior layout while HCM is offline. |
| Five approved card types and bounds | IMPLEMENTED | Existing compiler plus Pass 7 layout with button, slider, entity, entities, thermostat. |
| HCM-authoritative commands and duplicate protection | IMPLEMENTED (simulation); PARTIAL (physical feedback) | Simulator returns IDs, duplicate rejection, unavailable state, and `physical_success=False`; no physical success is claimed. |
| Sonic/SVR1 session contract | IMPLEMENTED (deterministic simulator) | Session metadata identifies panel/area and `transport=SVR1`; transcription dispatch is simulated. No ASR claim. |
| Global mute policy | IMPLEMENTED (simulation) | Starts muted, expires/rejects policy, disconnects muted, terminates active session on mute. |
| SIM/RMC independence | IMPLEMENTED for simulator; PARTIAL repository retirement | Pass 2 deprecation remains additive and rollback-safe; see `PASS_07_LEGACY_RETIREMENT.md`. |
| ESP32-P4/W5500/audio/touch hardware | HARDWARE_BLOCKED | See `PASS_07_HARDWARE_BLOCKERS.md`. |
