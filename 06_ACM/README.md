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
display boundary in `03_Shared/board_config.h`; the keypad firmware remains
buildable until the selected controller is physically confirmed. The UI state
model is represented by the alarm protocol states and keypad intent messages;
LCD drawing and touch scanning are the next hardware-specific layer.

## Alarm and configuration model

The ACM is authoritative for `DISARMED`, `ARMED_HOME`, `ARMED_AWAY`,
`ARMING_DELAY`, `ENTRY_DELAY`, `TRIGGERED`, and `TROUBLE`. ARM HOME is
immediate; ARM AWAY uses a 30-second nonblocking arming delay. Opening sensors
start a 30-second entry delay, while motion requires 10 seconds of continuous
activity in ARM AWAY. Sensors open at arm are bypassed until restored and then
resume monitoring automatically.

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

`03_Shared/protocol.*` uses bounded big-endian length-prefixed JSON frames with
a version and message type. HCM `ACM_STATUS` is deliberately compact and
contains only global state, countdown, trouble, device identity, and sequence;
sensor truth remains owned by the ACM. The ACM sends state changes, reconnect
state, countdown updates, and a complete snapshot every 60 seconds.

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

## Keypad UI V1

The keypad uses a 480x320 landscape layout defined by `02_Keypad/ui_model.h`
and a driver-neutral controller in `02_Keypad/ui_controller.h`. HOME always
keeps separate touch targets for digits 0-9, backspace, and enter. Header
controls open Alerts and Settings. Armed, delay, entry, and triggered states
retain the keypad; the physical panic input remains GPIO-only. The reference
renders in `03_Shared/images/` are regenerated from this layout contract.

The numeric keypad is one reusable `NumericKeypadComponent`. Its 12 key
regions and labels are identical for disarm, master PIN, first-boot
provisioning, settings authentication, and entry-delay flows.

The LCD and touch hardware driver is intentionally still behind the
`KeypadDisplay`/`KeypadTouch` boundary until the exact controller and touch
coordinates are bench confirmed.

## V1 audible alarm outputs

ACM relay outputs 1-8 are active-low: HIGH is inactive and LOW is active.
Only relays whose persisted `RelayRecord.siren` flag is true are owned by the
alarm siren policy. They activate on `TRIGGERED` and clear immediately on
`DISARMED`; generic contact relay state is left untouched. Changes to the
persisted siren designation are reconciled while the alarm is running.

The ACM sends framed `LOCAL_SIREN_ON` and `LOCAL_SIREN_OFF` commands to every
connected keypad. The keypad 5 V MOSFET siren is off before network
initialization, stays continuously on only during `TRIGGERED`, and is cleared
immediately on disarm or reconnect reconciliation. The separate 3.3 V piezo
only provides short acknowledgement tones and one short chirp per second while
`ARMING_DELAY` or `ENTRY_DELAY` countdown seconds change. It is stopped in all
other alarm states and is never used as the continuous alarm sounder.

## V1 event logging and time

ACM is the authoritative audit logger. It follows the time hierarchy
`HCM → ACM → keypads`: ACM requests UTC over its existing framed HCM
connection, applies `America/Detroit` (`EST5EDT` with local DST rules), and
sends valid time to authorized keypads after snapshot synchronization. Alarm
operation does not wait for time; unsynchronized entries use an `UNSYNC+...ms`
monotonic marker and never fabricate a calendar date.

ACM and keypad logs use `/logs/YYYY-MM.log` after synchronization and write one
`*****` date separator per local date during a run. Keypad-only events remain
minimal. SD initialization is centralized in the logger with retry backoff;
SD loss sets trouble state but does not stop sensors, networking, alarm logic,
or sirens. HCM and keypad communication, sensor, alarm, siren, fault, and time
transitions are logged once at their transition boundaries.

## Embedded administration UI

The ACM serves a local HTTP administration interface on port 80 over the
trusted management network. It uses Master-PIN-only login, an ephemeral
server-side session with a five-minute idle timeout, an HttpOnly/SameSite
cookie, CSRF-protected configuration POSTs, bounded request parsing, and
escaped HTML rendering. The interface provides Channels, Outputs, Areas,
Keypads, PINs, System, Logs, and Logout pages backed by the live ConfigStore,
PinStore, AlarmCore, KeypadManager, and EventLogger. Firmware updates remain
USB-only; V1 does not provide OTA or HTTPS.
