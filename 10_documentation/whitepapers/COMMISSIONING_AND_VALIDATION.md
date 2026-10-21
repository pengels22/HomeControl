# HomeControl Commissioning and Validation Manual

**Audited software baseline:** `6fc4179c3a2671fc66c81dc9f69d320ee2420f8f`

## Purpose

This manual defines the intended progression from approved design to physically commissioned HomeControl hardware.

Automated software-test success is not physical commissioning.

## Lifecycle states

### UNVERIFIED

The hardware mapping or design has not been validated.

Normal physical energization is not permitted.

### DESIGN_APPROVED

The intended design is accepted.

Physical output remains disabled.

### BENCH_TESTING

The module is undergoing explicit hardware-in-the-loop validation.

Normal HCM and module API commands remain unable to energize outputs.

Only explicit HIL tooling may actuate the selected target and channel.

### BENCH_TESTED

The required bench tests have passed, but the module is not yet considered fully commissioned for installed operation.

### COMMISSIONED

The complete module is approved for normal physical operation, subject to all runtime gates.

### SIMULATED

The profile or environment is intentionally nonphysical.

## Module-level commissioning

Commissioning applies to the module as a unit.

There is no production per-channel commissioning list.

Once a module is COMMISSIONED, channels defined by its authoritative hardware profile are part of the commissioned inventory.

Unknown channels remain invalid.

## Normal physical-output gate

Normal physical energization requires all of the following:

1. `io.mode == real`;
2. module `verification.status == COMMISSIONED`;
3. module `physical_output_enabled == true`;
4. requested channel exists in the authoritative hardware profile;
5. the relevant output section has `real_output_enabled == true`;
6. safety and maintenance arbitration permits energization;
7. the HCM binding durably selects `execution_mode: physical`.

HCM and the module independently enforce their parts of this contract.

## Bench-test authorization

BENCH_TESTING does not weaken the production gate.

Bench tooling requires explicit opt-in and an exact target and channel.

The initial commissioning process must not use wildcard or all-channel activation.

The repository runner is `13_hardware_tests/hil_runner.py`. It is inert unless
all of these values are supplied explicitly:

```sh
export HCM_HARDWARE_TESTS=1
export HCM_HARDWARE_TARGET=RCM       # RCM or LCM
export HCM_HARDWARE_SCOPE=channel   # channel or module
export HCM_HARDWARE_CHANNEL=A1      # required for channel scope
export HCM_HARDWARE_I2C_BUS=3       # explicit Linux bus; never guessed
python 13_hardware_tests/hil_runner.py
```

For a full module run, omit `HCM_HARDWARE_CHANNEL` and select
`HCM_HARDWARE_SCOPE=module`. RCM's optional group pattern requires the separate
explicit `HCM_HARDWARE_PATTERN=all` setting. The runner creates an in-memory
`BENCH_TESTING` profile view, uses production driver classes, records latch/PWM
readback, and always attempts final all-off cleanup. It never changes the
repository profile or marks a module commissioned.

## First RCM bench test

The recommended first physical test is one isolated RCM relay output.

Prerequisites:

- exact audited software commit pinned;
- hosted CI green;
- explicit Linux I2C device identified;
- expected relay-card addresses verified;
- safe test load only;
- no HVAC or installed-house load connected;
- module placed into BENCH_TESTING outside repository defaults.

Recommended sequence:

1. open the explicitly configured I2C transport;
2. detect the expected relay expanders;
3. initialize outputs to safe OFF;
4. choose one approved test channel;
5. verify output-latch OFF;
6. command ON;
7. verify output-latch ON;
8. observe the external meter, indicator, or isolated test load;
9. command OFF;
10. verify output-latch OFF;
11. independently confirm the external test load is OFF;
12. force OFF again during cleanup.

Do not automatically iterate all 32 relays during the first test. After the
single-channel result is reviewed, an explicit module-scope run may iterate all
32 relays in canonical A1-D8 order.

## RCM acceptance record

Record at minimum:

- date/time;
- module device ID;
- software commit;
- hardware-profile revision;
- Linux I2C device;
- relay-card addresses;
- selected channel;
- commanded state;
- output-latch readback;
- external physical observation;
- cleanup/safe-off result.

## LCM commissioning

LCM should be validated by output class.

### Relay outputs

Confirm:

- MCP23017 channel mapping;
- active-low behavior;
- startup safe state;
- physical switching with an isolated test load.

### 0-10 V outputs

For representative channels:

- command defined percentages;
- measure output voltage;
- verify monotonic scaling;
- verify 0% safe state;
- confirm no unintended startup pulse.

### Shelly high-voltage dimmers

Before physical commissioning:

- bind permanent device identity;
- verify network endpoint;
- verify component mapping;
- verify authenticated RPC behavior;
- verify OFF behavior;
- verify device-reported state.

Do not treat RPC response alone as proof of downstream mains/load state.

## SIM commissioning

SIM should be commissioned in separate stages:

- CAN physical layer;
- CAN receive/telemetry;
- analog inputs;
- DIO;
- switched 12 V outputs.

Physical ADC, DIO, and switched-12 V implementations are not yet complete, so those portions are not ready for final physical commissioning.

## RMC commissioning

RMC telemetry can be validated independently of firmware-update support.

Physical CAN firmware update must remain blocked until the bootloader path implements and proves:

- enter-bootloader;
- ready acknowledgement;
- block transfer;
- acknowledgement/rejection handling;
- retry;
- integrity verification;
- reboot;
- application-version verification.

## Fire-input commissioning

Fire GPIO commissioning is separate from RCM and LCM commissioning.

Verify:

- correct GPIO line;
- NO/C/NC wiring;
- normal LOW;
- alarm HIGH;
- startup HIGH recognition;
- startup LOW recognition;
- 250 ms transition debounce;
- physical authority prevents software override;
- unknown/disconnected input reports fault;
- AC-present input remains separate.

Initial validation should use a controlled dry-contact/electrical test fixture rather than actuating the installed building alarm system.

## Safety-off validation

Every real-output module must prove safe-off behavior.

Exercise software-controlled test conditions for:

- communication loss;
- maintenance lockout;
- fault handling;
- explicit all-off where applicable.

Confirm the initialized real driver receives OFF commands even when normal energization permission is unavailable.

## Network and supervision validation

Commissioning should also verify:

- current VLAN 20 development topology until a migration is explicitly approved;
- stable device ID;
- hostname;
- HCM control connection;
- Unified Heartbeat V3;
- Conflict acknowledgement;
- communication-loss behavior;
- duplicate-identity detection.

## Production release criteria

A module must not be marked COMMISSIONED solely because:

- unit tests pass;
- a driver initializes;
- an output register changes;
- the HCM UI displays an expected value.

Commissioning requires evidence appropriate to the actual electrical function.

## Documentation after commissioning

After each physical milestone, update:

- hardware-profile verification state;
- commissioning record;
- implementation-status white paper;
- known limitations;
- deployment/runbook material.

Target-specific credentials and secret material must remain outside version control.
