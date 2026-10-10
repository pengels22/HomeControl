# HCM Phase 3 Safety Arbitration

Phase 3 adds a software safety-arbitration layer for simulated and logical
output commands. It does not deploy hardware changes, alter GPIO drivers, or
prove electrical safety.

## Output Command Paths

Software paths capable of commanding controlled outputs:

- HCM logical device command API through `01_HCM/devices.py`.
- HCM HVAC output callbacks in `01_HCM/main.py`.
- HCM fire response in `01_HCM/safety.py`.
- RCM relay commands in `04_RCM/main.py`.
- LCM relay and dimmer commands in `03_LCM/main.py`.
- SIM Hexa DIO output and 12 V switching commands in `02_SIM/main.py`.
- Simulator endpoints in `10_scripts/simulate_homecontrol.py`.

All of these paths now pass through the shared arbiter in
`07_servises/common/safety_arbiter.py` before simulated module outputs are
changed or HCM dispatches a module command.

Digital inputs and analog inputs are explicitly not controlled outputs and are
not part of maintenance lockout. They must continue sensing/reporting during
lockout, fire, and fault conditions. In SIM, DIO channels configured with
`direction: input` reject output commands and can only be updated through
simulated input injection; AIO channels are read-only telemetry.

The dedicated HCM safety I/O is classified separately from normal module
outputs. `alarm_contact` is an input on physical pin 15/GPIO393. `door_request`
is a simulated dry-contact output on physical pin 16/GPIO256 and `auxiliary` is
a simulated output on physical pin 18/GPIO344. These HCM safety relays are not
normal automation outputs and are documented as lockout-exempt; API access still
requires an ADMIN session and real GPIO is not enabled in Phase 3.

## Priority Table

| Priority | Condition/source | Effective behavior |
|---|---|---|
| 1 | Maintenance Lockout | Final command is de-energized. Fire may still be detected and reported, but cannot energize a controlled output. |
| 2 | Fire / Life Safety | Emergency lighting channels may energize only when lockout is inactive. HVAC shutdown relay coils are commanded de-energized. |
| 3 | Local Override | Wins over user/rules/schedule/scene requests unless an applicable safety condition is active. |
| 4 | HCM user, rules, schedules, scenes | May command outputs only when no higher-priority inhibit applies. |

Commands received during maintenance lockout are not recorded as active HCM
intents. Clearing lockout therefore does not replay stale energize requests.

## Output State Model

Every arbitration decision exposes:

- `device_id`
- `channel_id`
- requested state
- effective state
- feedback state, when available
- control source
- active safety conditions
- last transition timestamp
- fault state

Dimmer de-energized state means zero commanded drive. Relay de-energized state
means relay-coil command off; it does not prove the field circuit is off.

## State Machine

| State | Entry | Output behavior | Recovery |
|---|---|---|---|
| Normal | No active safety conditions | Requests follow source priority. | N/A |
| Maintenance lockout | Admin lockout set or local module safety state received | Applicable outputs are commanded de-energized. No lower source can energize. | Clear lockout deliberately; stale requests are not replayed. |
| Fire active | Debounced fire alarm active or HCM fire API active | Emergency lighting only if configured and lockout inactive. HVAC shutdown relays de-energized. | Clear fire deliberately; life-safety intents are cleared and current active lower-priority intent is reapplied through arbiter. |
| Fire with lockout | Fire active and maintenance lockout active | Fire is logged/reported. Outputs remain de-energized. | Clear fire and lockout independently. |
| Input fault/unknown | Fire input sample is unknown/disconnected in simulated input abstraction | Conservative de-energized output decision for affected requests. | Restore supervised input and clear fault. |
| Communication failure | Module receives communication-loss safety condition | Conservative de-energized output decision. | Restore safety-state communication and clear condition. |
| Arbiter fault | Arbiter malfunction condition active | Conservative de-energized output decision. | Diagnose and clear only after validation. |

## Fire Input

The simulated fire input abstraction is `07_servises/common/fire_input.py`.
Current documented contact arrangement:

- NO -> 3.3 V
- Common -> GPIO
- NC -> Ground

For a normally de-energized relay, expected interpretation is LOW = normal and
HIGH = fire alarm. The abstraction applies 250 ms debounce in tests/simulator.

Real GPIO remains disabled for this phase. Actual relay polarity, electrical
limits, input protection, and disconnected/floating behavior must be validated
before deployment.

## Global Configuration

Global defaults are loaded through `07_servises/common/global_config.py` from the
existing numbered configuration directories:

- `06_config/01_HCM/global_var.py`
- `06_config/02_SIM/global_config_SIM.py`
- `06_config/03_LCM/global_config_LCM.py`
- `06_config/04_RCM/global_config_RCM.py`
- `06_config/05_PNL/global_config_PNL.py`
- `06_config/06_RMC/global_config_RMC.py`

The loader validates required values and preserves file provenance. Runtime
integration in this phase uses HCM door pulse bounds and SIM Hexa 12 V restart
timing. The SIM and RMC CAN bitrate mismatch remains visible in tests and must
be resolved before any firmware/CAN deployment.

## Unified Heartbeat V3

`SafetyController` reports safety status and faults through the existing local
Heartbeat V3 Unix socket:

- maintenance lockout status
- fire alarm status/fault
- fire input fault
- inhibited fire output command

Failure of the local heartbeat daemon is logged/debug-only and does not disable
local arbitration.

## Fail-State Table

| Failure | Software behavior | Hardware validation still required |
|---|---|---|
| Maintenance lockout active | Command applicable outputs de-energized and inhibit energize requests. | Physical maintenance isolation and lockout/tagout. |
| Digital/analog input active during lockout | Inputs continue to report; no output arbitration is applied to DI/AI channels. | Input electrical conditioning and supervision. |
| HCM door request or auxiliary relay active during lockout | Dedicated HCM safety relays remain outside normal output lockout arbitration and require ADMIN API access. | Verify intended fire/access-control behavior, relay contact state, and hardwired interlocks. |
| Fire alarm active | Log/report fire, de-energize HVAC shutdown relay coils, energize configured emergency lighting only if not locked out. | Emergency lighting circuit assignment and hardwired fire/HVAC shutdown. |
| Fire input unknown | Conservative output inhibit in arbiter. | Supervised input circuit, pull resistors, protection, and fault detection. |
| HCM to module communication loss | Modules can receive/hold local `communication_loss` safety condition and de-energize. | Independent watchdog/fail-state behavior after processor/network loss. |
| Feedback mismatch | Arbiter marks `feedback_mismatch` when feedback is provided and disagrees. | Verified feedback wiring and contact interpretation. |
| Heartbeat V3 unavailable | Safety path continues; reporting degrades. | Conflict supervision and alerting behavior. |

## Hardware Boundary

Do not commission from software tests alone. Still required:

- MCP23017 relay-driver validation.
- Relay-coil versus NO/NC/common contact mapping.
- HVAC hardwired shutdown independent of HCM, Wi-Fi, or heartbeat.
- Fire and AC input electrical conditioning.
- Emergency lighting assignment list.
- GPIO boot/reset output states.
- Watchdog and processor-failure output behavior.
- Physical maintenance isolation requirements.

## Deployment And Rollback Plan

No Phase 3 deployment is authorized yet.

Deployment preparation:

1. Back up repository, service files, configs, PostgreSQL, and current module
   config templates.
2. Run full tests on a non-live host.
3. Validate simulated safety scenarios.
4. Review emergency lighting and HVAC shutdown channel configuration.
5. Validate hardware fail states separately.

Rollback:

1. Restore prior application/module code and config templates.
2. Restart HCM/module services in the lab only.
3. Confirm outputs remain de-energized before reconnecting field equipment.
4. Do not restore stale energize intents without operator review.
