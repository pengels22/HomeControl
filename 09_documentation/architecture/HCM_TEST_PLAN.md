# HCM Test Plan

This test plan records required coverage before changing production behavior.

## Network Tests

- Verify current templates do not use VLAN 60 for normal module control.
- Verify VLAN 40 values remain unset until an approved subnet exists.
- Verify provisioning examples use operator-supplied VLAN 20 addresses for the
  current development baseline.
- Verify registry assignment uses the active configured control-network profile
  rather than hardcoded `192.168.60.x` pools.
- Verify VLAN 60 cannot be selected as a module-control assignment profile.
- After VLAN 40 approval, verify registry assignment uses configured VLAN 40
  pools only after an explicit subnet and pools are entered.
- Verify Heartbeat V3 uses TCP 6004 and targets Conflict Manager
  `192.168.60.2` only after VLAN 60 is enabled.

## Device Identity Tests

- Normalize `48:b0:2d:87:db:16` to `48b02d87db16`.
- Reject non-hex, too-short, too-long, and UUID-shaped IDs.
- Verify module identify/assignment uses `device_id`, not generated
  `module_uuid`.
- Verify PostgreSQL writes and reads preserve 12-hex text IDs.
- Verify fault history and device bindings remain attached during a
  non-destructive legacy UUID to device ID transition.
- Verify replacement/recommissioning links old and new physical IDs without
  deleting history.

## Heartbeat Tests

- Verify Heartbeat V3 emits normalized `device_id`.
- Verify Conflict allowlists compare normalized IDs.
- Verify `identity_interface` can differ from the interface carrying heartbeat
  traffic.
- Verify missed Conflict responses mark peer offline without contaminating local
  service health.
- Verify registry current reachability remains separate from last-known status
  and fault history.
- Verify module agents report application status, HCM TCP session status,
  faults, and watchdog pulses through the single local V3 daemon socket.
- Verify a healthy HCM TCP session does not mask an overdue application
  watchdog in V3 health.

## Maintenance Lockout And Fire Tests

Required before safety behavior changes:

- User command cannot energize an output while maintenance lockout is active.
- Rules command cannot energize an output while maintenance lockout is active.
- Local override cannot energize an output while maintenance lockout is active.
- Simulated fire alarm cannot energize emergency lighting while maintenance
  lockout is active.
- Fire event is still logged while maintenance lockout is active.
- Fire notification/fault reporting is attempted while maintenance lockout is
  active.
- When maintenance lockout is inactive, simulated fire alarm requests approved
  emergency lighting and HVAC shutdown final states.
- Requested output state and final output state are both visible in testable
  data structures.
- Tests assert that no hardware-driver-facing energize command is emitted during
  maintenance lockout.

## Hardware Validation Tests

These are not simulator-only tests:

- Relay active-high/active-low behavior.
- Relay contact NO/NC/common mapping.
- Whether de-energized relay state actually turns connected equipment off.
- Fire input relay polarity and debounce.
- HVAC shutdown relay contact behavior and hardwired interlock behavior.
- LCM 0-10 V output scaling.
- MCP23017 addressing and fail state.
- CAN bitrate agreement between SIM and RMC.

Do not treat passing software tests as hardware safety certification.
