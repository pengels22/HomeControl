# HCM Safety Architecture

This document records safety requirements and current implementation status.
It does not certify any life-safety function.

## Core Principle

Life-safety behavior must remain independent of convenience automation and
ordinary network availability. Software heartbeat monitoring is supervisory
telemetry, not a certified life-safety mechanism.

Safety-critical behavior must not depend on:

- Wi-Fi availability.
- Public Internet access.
- iOS push delivery.
- HCM web UI availability.
- Unauthenticated heartbeat messages.
- A direct app-to-module control path.

## Fire Monitoring

Current repository state:

- `01_HCM/safety.py` implements a software fire-state controller that can be
  triggered through the authenticated API.
- `06_config/01_HCM/Pinout.md` documents fire input reference, GPIO, and ground
  pins.
- No production GPIO fire-input driver was found.
- `09_documentation/PINNED_ARCHITECTURE.md` says HIGH is normal and LOW is fire
  active.
- The newer brief says the latest SPDT relay arrangement should produce normal
  LOW and alarm HIGH if the relay is normally de-energized.

Unresolved safety contradiction:

- Fire input polarity conflicts between existing pinned documentation and the
  newer hardware brief. Do not implement the fire input driver until this is
  resolved with actual relay behavior and input conditioning.

Required future validation:

- Relay contact arrangement and normal/alarm state.
- Pull-up/pull-down behavior.
- Electrical isolation and voltage/current compatibility.
- GPIO protection.
- Loss-of-wire behavior.
- Debounce target, currently briefed as approximately 250 ms.
- Fail behavior on HCM crash, processor power loss, or network failure.

## Fire Response

Current software response in `SafetyController.set_fire(True)`:

- Latches `fire_active` in memory.
- Inserts a row into `safety_events`.
- Calls `hvac.force_off()`.
- Sends a critical notification through the notification abstraction.
- Selects enabled logical devices with `device_class='light'` and
  `maintenance_locked=false`.
- Commands those lights to 100 percent / on with source `life_safety`.

Limitations:

- Triggering is currently API/software-driven unless an external driver calls
  the controller.
- Fire active state is not loaded from persistent state on HCM restart.
- Light sweep depends on PostgreSQL, module connectivity, logical bindings, and
  module command delivery.
- HVAC shutdown through `hvac.force_off()` is a software command path, not a
  hardwired shutdown path.
- Notification delivery is not implemented as a production APNs/critical-alert
  path.

Required architecture:

- A real fire event must be able to override convenience automation.
- HVAC shutdown for fire must include an independent hardwired path.
- Software commands to connected HVAC controls are useful but secondary.
- Occupant/system notification is required but must not be the only protective
  action.

## Maintenance Lockout

Approved output priority:

1. Maintenance Lockout.
2. Fire/Life Safety.
3. Local Override.
4. HCM rules/user commands.

Current Phase 3 code represents maintenance lock as a boolean on
`logical_devices` and routes requested commands through the shared safety
arbiter in `07_servises/common/safety_arbiter.py`. The arbiter returns both the
requested state and the effective commanded state. Maintenance-locked logical
commands produce a de-energized effective command and are not recorded as active
output intents, so clearing lockout does not replay stale energize requests.

Maintenance lockout is explicitly part of the life-safety architecture and is
the highest-priority output inhibit. When it is active:

- No controlled output may energize.
- Fire-response commands may not override maintenance lockout to energize an
  output.
- Normal automation, local overrides, and remote commands may not energize
  outputs.
- Fire detection and fault reporting must continue.
- Fire events must still be logged and communicated where possible.

When maintenance lockout is inactive and a fire alarm occurs:

- Designated emergency lighting outputs are energized.
- Appropriate HVAC shutdown relay outputs are de-energized.
- Normal HCM automation is overridden as required by the approved fire-response
  design.

The software must distinguish requested output state from the final output state
after safety arbitration.

## HVAC Safety

Pinned HVAC behavior:

- HCM is the thermostat.
- Modes: HEAT, COOL, FAN, OFF.
- Damper command, 500 ms delay, fan, 500 ms delay, heat/cool call.
- COOL minimum run 2 minutes.
- HEAT minimum run 1 minute.
- Y and W restart lockout 5 minutes.
- Fan post-run 60 seconds.
- FAN runs until changed.
- OFF opens HVAC call relays.
- Failed room sensor causes that room damper to default open.

Current code implements the timing constants and state machine in
`01_HCM/hvac.py`, with tests for sequencing, OFF behavior, fan mode, minimum
run, restart lockout, and failed sensor damper fail-open.

Safety limitations:

- `force_off()` opens software-controlled calls through logical devices.
- The independent hardwired HVAC shutdown path described in the brief is not
  implemented in production hardware drivers.
- Actual relay polarity and fail-open/fail-closed electrical states need
  hardware validation.

## Conflict Manager Supervision

The Conflict Manager is independent supervisory hardware and should detect HCM
or device failures without requiring the primary HCM app. Unified Heartbeat V3
supports this model, but it does not certify safety behavior.

Requirements:

- Conflict Manager must boot unattended.
- It must run the heartbeat service through systemd.
- It must maintain current reachability separately from last-known health.
- It must not cause reciprocal fault cascades by treating peer faults as its own
  local health.

Current V3 implementation aligns with these principles, but peer registry
persistence and event auditing are not implemented.

## Output Priority

Current code implements priority using active output intents:

- `life_safety`: rank 300.
- `local_override`: rank 200.
- `user`: rank 100.
- `rules`: rank 100.

Maintenance lock is not an output intent; it blocks commands before intent
application. This effectively makes it higher than life safety for
logical-device commands.

Maintenance lockout remains above fire/life safety and this ordering must not
change without explicit approval.

## Required Before Production

- Resolve fire input polarity and debounce.
- Implement and test independent hardwired fire/HVAC safety paths.
- Add tests proving no output receives an energize command while maintenance
  lockout is active, including during simulated fire alarms.
- Validate relay fail states and active-high/active-low behavior.
- Document contact states, fail-safe behavior, and required hardwired interlocks.
- Do not assume relay de-energization guarantees connected equipment is off.
- Separate life-safety outputs from convenience-only outputs where required.
- Define safety event latching, reset, audit, and operator indication.
- Test processor restart, network outage, module outage, and PostgreSQL outage
  safety behavior separately from simulator-only tests.
