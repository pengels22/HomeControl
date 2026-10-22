# HomeControl Life-Safety and Safety Arbitration White Paper

**Audited software baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`

## Purpose

This paper defines the approved HomeControl safety model, including fire detection, maintenance lockout, emergency lighting, HVAC shutdown, safety arbitration, and the distinction between software command state and physically verified state.

It describes the software architecture and approved electrical semantics. It does not claim that physical fire, relay, HVAC, or lighting hardware has been commissioned.

## Safety authority hierarchy

For controlled outputs, the effective priority is:

1. Maintenance lockout
2. Fire / life safety
3. Local override
4. Normal HCM commands, schedules, scenes, and future rules

Maintenance lockout is therefore an inhibit above life-safety energization.

This does not mean maintenance lockout disables sensing. Fire detection, status, fault reporting, event recording, and supervision continue while the lockout is active.

## Two maintenance-lockout scopes

HomeControl deliberately has two different maintenance concepts.

### System / life-safety maintenance lockout

This is owned by the HCM safety controller.

Purpose:

- wiring and maintenance work;
- system-level safety-output inhibition;
- preventing an accidental fire response from energizing controlled outputs during maintenance.

The HCM API exposes a dedicated ADMIN-only system-maintenance-lockout path.

The system lockout does not clear or hide fire detection.

### Logical-device maintenance lockout

This belongs to a specific logical output.

Purpose:

- servicing one controlled device;
- preventing a specific output from energizing;
- preserving the rest of the system's normal operation.

The two lockout types must never be conflated.

## Fire input electrical contract

Authoritative FIRE relay wiring:

- NO -> 3.3 V
- C -> GPIO
- NC -> GND

Assuming the smoke relay is normally deenergized:

- normal = LOW
- alarm = HIGH

Software uses a 250 ms transition debounce.

The physical contact remains the safety authority. There is no software latch that can override a physical HIGH alarm or force the contact back to normal.

When the Linux physical fire backend is authoritative, the simulation API refuses to clear or replace the physical fire state.

## Fire startup behavior

The controller must not wait for a transition before recognizing initial state.

At startup:

- initial HIGH is treated as active fire;
- initial LOW is treated as normal;
- unknown/unreadable input is reported as fault/unknown rather than normal.

## AC-present monitor

The AC-present monitor is independent from the fire alarm contact.

Its state may report power presence/loss but must not be converted into a fire event.

The physical implementation uses a separate relay pole/contact path per processor where applicable.

## Fire response sequence

When a fire becomes active, HCM:

1. records the safety event;
2. updates heartbeat/supervisory fire status;
3. initiates HVAC shutdown;
4. records a critical notification;
5. commands designated emergency lighting when the system maintenance lockout permits it.

Emergency lighting is selective. HomeControl does not indiscriminately turn on every light.

Emergency-light designation comes from explicit configuration or logical-device metadata.

## HVAC shutdown

Fire response invokes the HCM HVAC `force_off()` path.

The controller independently attempts:

- COOL OFF
- HEAT OFF
- FAN OFF

A failure commanding one output does not prevent attempts on the remaining outputs.

The result reports failures truthfully.

There is no software-controlled master HVAC disconnect relay in the current approved architecture.

## Safe-off authority

HomeControl distinguishes authorization to energize from authority to deenergize.

Normal physical energization requires full commissioning and physical-output gates.

Safety deenergization is different:

- if a real physical driver is already initialized;
- and its output mapping is known;

the system may command that output OFF even when normal energization would be prohibited.

This prevents a commissioning flag, lockout transition, or configuration error from blocking a required safe-state command.

## RCM local safety

For initialized real RCM hardware, local safety events can command all known relay outputs OFF.

Relevant safety conditions include:

- maintenance lockout;
- fire-input fault;
- communication loss;
- arbiter fault;
- explicit all-off.

The software attempts all outputs and records failures rather than stopping after the first error.

## LCM local safety

For initialized real LCM hardware, local safety shutdown attempts safe state across:

- relay outputs;
- 0-10 V PWM outputs;
- configured Shelly high-voltage dimmers.

One component failure does not prevent later safe-off attempts.

## Safety arbitration

HCM stores requested intent separately from effective output state.

A safety arbiter evaluates:

- source priority;
- maintenance state;
- fire state;
- local conditions.

A command suppressed by maintenance lockout is converted into a deenergized effective command and is not retained as a stale energize request that automatically replays when lockout clears.

## State confidence

Safety decisions must not overstate the evidence available.

Supported confidence classes include:

- SIMULATED
- COMMANDED
- OUTPUT_LATCH_READBACK
- DEVICE_REPORTED
- PHYSICAL_FEEDBACK
- UNKNOWN

An I2C output register readback proves the hardware output latch state, not the downstream relay contact or load state.

A Shelly RPC response proves device-reported state, not independent electrical confirmation.

Only independent sensing justifies PHYSICAL_FEEDBACK.

## Notification truthfulness

Fire notification text reports actions as initiated, not physically confirmed.

Current software records the critical notification event but does not yet provide the production mobile/watch delivery adapter.

The companion app is the intended future delivery endpoint for user notifications.

## Maintenance testing rule

The system maintenance/LOT lockout is the intended software maintenance inhibit for wiring and bench work.

It must not erase fire detection or status.

Physical hardware bench testing must still use the dedicated HIL test framework and explicit selected target/channel controls.

## Hardware status

Software behavior is tested.

Physical commissioning remains outstanding for:

- HCM fire GPIO;
- physical relay polarity/state;
- RCM hardware;
- LCM hardware;
- HVAC field wiring;
- emergency-light field behavior.

No software test alone certifies a life-safety installation.
