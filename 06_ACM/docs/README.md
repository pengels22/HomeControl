# ACM and alarm keypad V1

This directory contains real ESP32-S3 firmware targets, not a simulator. Both
targets use PlatformIO and the Arduino ESP32 framework:

```sh
pio run -d 06_ACM -e acm
pio run -d 06_ACM -e keypad
pio run -d 06_ACM -t upload -e acm
```

The selected environment is `esp32-s3-devkitc-1`; board-specific vendor
definitions can be substituted in `platformio.ini` without changing alarm
logic. The firmware is standalone-first. Ethernet/HCM loss sets a trouble bit
and retries without stopping local sensor processing, alarm policy, logging, or
keypad intent handling.

## Hardware assumptions

The W5500 uses CS 10, MOSI 11, MISO 12, SCK 13, reset 9, and interrupt 14.
The onboard SD SPI uses CS 4, MISO 5, MOSI 6, and SCK 7. ACM I2C uses SDA 8
and SCL 18. Two MCP23017 devices default to 0x20 (24 inputs) and 0x21
(8 inputs plus 8 relays). ACM logical inputs are `input.01` through
`input.24`; relays are `relay.01` through `relay.08`. Keypad inputs are
`input.01` through `input.08`, with panic GPIO 16, piezo GPIO 17, and the
MOSFET siren control GPIO 15.

The exact LCD controller and touchscreen pinout are intentionally behind a
display boundary in `shared/board_config.h`; the keypad firmware remains
buildable until the selected controller is physically confirmed. The UI state
model is represented by the alarm protocol states and keypad intent messages;
LCD drawing and touch scanning are the next hardware-specific layer.

## Alarm and configuration model

The ACM is authoritative for `DISARMED`, `ARMED_HOME`, `ARMED_AWAY`,
`EXIT_DELAY`, `ENTRY_DELAY`, `TRIGGERED`, and `TROUBLE`. Force-arm semantics
use per-sensor bypass bits and restore monitoring independently when each input
closes. Timers are nonblocking and use `millis()` in the production loop.

PINs are ACM-only. `PinStore` uses an ESP32 NVS namespace, a random 16-byte
salt, and PBKDF2-HMAC-SHA256. The first accepted PIN provisions the master;
additional PIN storage requires master authentication. PINs, hashes, and salts
are never logged or sent to keypads. The current V1 storage schema is carried
by the NVS namespace and is ready for an explicit version key before field
migration.

Areas, stable sensor IDs, friendly names, polarity, debounce, and relay
function configuration belong in the ACM configuration store. SD is only for
rotating logs; missing or full SD raises a trouble bit and never prevents alarm
operation. ACM logs authoritative alarm events; keypads log only local sensor
fault/restored records.

## Protocol

`shared/protocol.*` uses bounded big-endian length-prefixed JSON frames with a version and message
type. Keypad intents include `PANIC` and the arm/disarm/settings family;
production ACM responses are `AUTH_RESULT`, `ALARM_STATE`, `OPEN_SENSOR_LIST`,
`FAILED_SENSOR_LIST`, `AREA_SUMMARY`, `COUNTDOWN`, `CONFIG`, and siren/piezo
commands. The ACM sends `ACM_STATUS` immediately on state or bitmap changes and
also sends a complete snapshot every 60 seconds. Open and failed state are
three 32-bit words, supporting at least 80 sensors without repeating names.

The heartbeat envelope carries device ID, hostname, sequence, health, and
status. It is intentionally separate from alarm status. HCM ACK loss never
blocks local operation. The transport boundary is ready to be upgraded to the
existing HCM authenticated framed transport when the device certificate and
deployment endpoint are provisioned; no plaintext credentials are embedded.

## Current TODOs requiring hardware verification

- Confirm the exact ESP32-S3 Ethernet/PoE board variant and its PHY reset/INT
  behavior.
- Confirm MCP23017 interrupt wiring and sensor polarity/termination.
- Confirm relay board active polarity and safe inactive state.
- Select and bench-test the LCD/touch controller and fill its pin constants.
- Validate the MOSFET gate level and 5 V siren wiring.
- Flash each board and verify Ethernet, SD, NVS, watchdog, and recovery timing.

No hardware-in-the-loop or physical flashing is claimed by this repository pass.
