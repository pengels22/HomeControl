# Hardware Integration Readiness

This phase adds production-shaped, fail-closed interfaces only. It does not
commission or deploy physical outputs.

## Modes

- `simulated`: in-memory module state; the default, including `io.mode: auto`.
- `mock`: production driver classes with recording transports; no Linux devices
  or network RPCs are opened.
- `real`: explicit Linux transports. Startup fails if the required transport is
  unavailable; there is no mock fallback.
- `disabled`: no hardware driver is constructed.

Driver construction is not authorization. A physical output request still
requires real I/O mode, profile verification status `COMMISSIONED`,
`physical_output_enabled: true`, a known channel in the authoritative output
section, and that section's `real_output_enabled: true`. Repository manifests
keep all physical-write gates disabled.

## State truthfulness

State reports distinguish simulated, commanded, output-latch readback, device
reported, physical feedback, and unknown confidence. Successful I2C/RPC
transport does not by itself prove electrical actuation.

## CAN and firmware

SIM receives only from explicitly configured `can0`, `can1`, or `can2` paths.
The mock and Linux SocketCAN transports share one interface. RMC telemetry is
marked stale after the configured timeout. Physical RMC firmware updates fail
closed until a verified bootloader/acknowledgment transport exists; simulation
updates remain available to fixtures.

## Fire inputs

The default HCM safety backend remains simulated. Selecting
`HCM_SAFETY_INPUT_BACKEND=linux` requires `gpiod`, accessible configured GPIO
chips/lines, and permissions; startup fails rather than falling back. The
inputs retain their manifest mappings and 250 ms debounce. AC-power loss is
reported separately and is not converted into a fire event.

## Migrations and updates

Use `10_scripts/homecontrol-db status` or `migrate` as an explicit deployment
step. Normal HCM startup does not mutate PostgreSQL schema. Enabled update
services require a durable SQLite replay store under `/var/lib/homecontrol`
and reject requests if it cannot be created or accessed.

## Test classifications

Normal CI uses simulated and mock fixtures only. `12_hardware_tests/` is
skipped unless both `HCM_HARDWARE_TESTS=1` and `HCM_HARDWARE_TARGET` are set.
The current opt-in test stops at the commissioning gate; no channel is
energized. System-test stress is synthetic and must not be described as live
HCM or Conflict request traffic.
