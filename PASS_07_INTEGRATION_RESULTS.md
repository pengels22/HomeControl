# Pass 7 simulated integration results

The deterministic test fixture creates `PNL-001` (Living Room), `PNL-002`
(Kitchen), and `PNL-003` (Bedroom), publishes one shared five-card dashboard,
assigns it by area, and connects all three panels concurrently.

| Scenario | Result | Test evidence |
|---|---|---|
| Registration, identity, area assignment | PASS | `test_three_panels_register_assign_report_and_render_independent_locals` |
| Independent local values and dashboard aliases | PASS | Same test; values 20/21/22 remain panel-scoped |
| Telemetry and heartbeat V3 | PASS | Same test plus independent freshness test |
| Immediate occupancy and deduplication | PASS | `test_occupancy_is_immediate_and_heartbeat_is_independent_from_telemetry` |
| Button/slider/entity/thermostat command authority | PASS | `test_commands_are_hcm_authoritative_and_duplicate_safe` |
| HCM outage and last-known-good display | PASS | `test_dashboard_update_and_sonic_svr1_session_survive_reconnect_boundaries` |
| Published update recovery | PASS | Same test verifies changed layout hash after reconnect |
| Global mute and active voice termination | PASS | Same test verifies session rejection after mute |
| Unauthorized panel and invalid revision/layout | PASS | `test_unauthorized_identity_and_invalid_revision_are_rejected` |

The scenario is software-only. It does not validate physical GPIO, W5500,
microphone disconnect, LVGL rendering, or a configured Whisper service.
