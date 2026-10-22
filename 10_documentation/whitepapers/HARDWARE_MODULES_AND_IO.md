# HomeControl Hardware Modules and I/O White Paper

**Audited software baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`

## Purpose

This paper describes the current HomeControl module hardware contracts and the software paths that operate them. It distinguishes physical-driver support from physical commissioning.

## ACM — Alarm Control Module

ACM uses the ESP32-S3 target and the following software pin contract:

| Function | Pins/addresses |
|---|---|
| W5500 | CS 10, MOSI 11, MISO 12, SCK 13, RESET 9, INT 14 |
| SD | CS 4, MISO 5, MOSI 6, SCK 7 |
| I2C | SDA 8, SCL 18 |
| MCP devices | `0x20` local inputs, `0x21` relay bank |
| Keypad | Panic GPIO16, piezo GPIO17, 5 V siren GPIO15 |

ACM local and keypad inputs use pull-ups with `LOW = CLOSED` and `HIGH = OPEN`.
Both paths require 250 ms stable-state debounce. ACM has 24 local alarm inputs,
up to 7 enrolled PoE keypads with 8 inputs each, and 8 active-low relay
outputs. Software initializes ACM relay outputs HIGH before enabling the output
direction and initializes the keypad 5 V siren OFF. These are software safety
intentions and still require physical validation.

## Hardware mode model

Common module hardware modes are:

- simulated;
- mock;
- real;
- disabled.

`auto` resolves to simulated.

There is no silent real-to-mock fallback.

Real hardware construction fails closed when required transport configuration is missing.

## RCM

### Function

RCM is the general-purpose relay module.

### Channel inventory

32 user-facing outputs:

- A1-A8
- B1-B8
- C1-C8
- D1-D8

### Active relay topology

The current source of truth uses two XL9535 16-bit I/O expanders:

- relay_card_1: I2C address 0x20
- relay_card_2: I2C address 0x21

Channel mapping:

- A/B banks -> relay_card_1
- C/D banks -> relay_card_2

Outputs are active-low according to the current hardware profile.

### Physical software path

Real mode:

LinuxI2CTransport -> LockedI2C -> XL9535RelayDriver

The real Linux I2C device/bus must be explicitly configured.

The software does not assume `/dev/i2c-1`.

### Safe behavior

Repository defaults:

- profile status DESIGN_APPROVED;
- `physical_output_enabled: false`;
- relay `real_output_enabled: false`.

Local safe-off can command initialized real relay outputs OFF regardless of normal energizing permission.

## LCM

### Function

LCM is the lighting-output module.

### Relay channels

- A1-A8

Current relay backend:

- MCP23017-based output path

### 0-10 V channels

- 10-1 through 10-10

Current active topology:

- PCA9685 PWM controller at address 0x40;
- channels 0-9 used for the ten user-facing outputs;
- channels 10-15 reserved.

Older documents describing eight MCP4725 DAC outputs are superseded.

### High-voltage dimmers

- HV-1 through HV-4

Current logical mapping:

- HV-1 -> shelly_1 / light:0
- HV-2 -> shelly_1 / light:1
- HV-3 -> shelly_2 / light:0
- HV-4 -> shelly_2 / light:1

The real Shelly device identities/endpoints are not yet commissioned.

### Safe behavior

LCM local safety shutdown attempts:

- relay OFF;
- PWM 0%;
- configured Shelly OFF/0%.

Failures are aggregated rather than aborting the rest of the shutdown sequence.

## SIM

### Function

SIM is the sensor and CAN gateway.

### CAN

Configured interfaces:

- can0
- can1
- can2

Bitrate:

- 125000 bit/s

The audited software includes a real AF_CAN/CAN_RAW receive path.

### Hexa analog inputs

Configuration describes ADS1115-based analog inputs and loop monitors.

Physical production ADC transport/scaling is not yet fully implemented.

### Hexa DIO

The configuration contains input/output direction models.

Physical DIO backend remains incomplete.

### Switched 12 V

The configuration models three switched loop outputs.

Physical switched-12 V output transport/mapping remains incomplete.

## RMC

RMC is a CAN sensor node rather than a Linux field module.

The sensor architecture includes:

- AHT21 temperature/humidity;
- ENS160 air quality;
- BH1750 ambient light;
- RCWL-0516 presence;
- CAN interface.

SIM decodes RMC CAN telemetry and tracks freshness.

## PNL

PNL is currently a logical panel agent.

It carries:

- room;
- dashboard URL;
- refresh interval;
- brightness setting;
- authentication requirement.

The complete LCD/touch/browser runtime is not represented solely by the PNL agent and remains a separate integration area.

## HCM safety GPIO

The HCM has a Linux gpiod-backed safety input path.

Physical FIRE relay semantics:

- NO -> 3.3 V
- C -> GPIO
- NC -> GND
- normal LOW
- alarm HIGH

Physical GPIO remains uncommissioned.

## State evidence

Hardware write/readback must use the correct confidence level.

- output register/latch readback does not prove relay contact state;
- device RPC response does not prove downstream electrical load;
- independent sensing is required for PHYSICAL_FEEDBACK.

## Commissioning

Commissioning is per module.

A COMMISSIONED module makes its authoritative profile inventory eligible for physical control, but normal physical output still requires:

- real mode;
- physical output enabled;
- relevant section real-output enabled;
- known channel;
- safety authorization.

There is no normal per-channel commissioning allowlist.

## Bench-test model

BENCH_TESTING is distinct from COMMISSIONED.

Ordinary HCM commands remain unable to energize a BENCH_TESTING module.

The explicit HIL test harness requires exact target and channel selection.

## Current hardware readiness

Software-ready for controlled bench work:

- RCM real relay path;
- LCM relay/PWM transport architecture;
- SIM CAN receive path;
- HCM fire-input software path.

Not yet physically validated:

- RCM I2C bus/device selection on target;
- relay electrical behavior;
- LCM relay/PWM hardware;
- Shelly identities/endpoints;
- SIM ADC/DIO/12 V;
- fire GPIO;
- installed CAN physical layer.
