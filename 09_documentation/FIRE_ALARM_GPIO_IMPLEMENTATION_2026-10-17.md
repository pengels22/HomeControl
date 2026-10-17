# Fire Alarm GPIO Inputs

Status: software implementation complete; physical wiring and live monitoring
remain uncommissioned.

Both controllers use the exact case-sensitive identifiers `fire_alarm_s` and
`fire_alarm_P`, with a 250 ms debounce. An unavailable or faulty input is
reported as `UNKNOWN`; it is never treated as normal.

## Approved mappings

| Controller | Sensor | Header pin | SoC/Linux mapping | HIGH means |
| --- | --- | ---: | --- | --- |
| HCM Jetson | `fire_alarm_s` | 38 | `/dev/gpiochip0`, line 159 | fire alarm active |
| HCM Jetson | `fire_alarm_P` | 40 | `/dev/gpiochip0`, line 158 | 120V AC present |
| Conflict Manager | `fire_alarm_s` | 38 | PI4, SoC GPIO 260, `/dev/gpiochip1`, line 260 | fire alarm active |
| Conflict Manager | `fire_alarm_P` | 40 | PI3, SoC GPIO 259, `/dev/gpiochip1`, line 259 | 120V AC present |

The HCM mappings were checked read-only with `gpioinfo`; the Conflict lines
were also present and unused during read-only inspection. No pinmux, overlay,
service, or live configuration was changed.

## Behavior

- HCM `fire_alarm_s` feeds the existing debounced `SafetyController` fire
  path, which retains the existing life-safety priority, HVAC shutdown,
  maintenance-lockout handling, and logical command arbitration.
- HCM `fire_alarm_P` is published as `present`, `absent`, or `unknown` and
  raises an input-health fault when unavailable. AC loss does not create a
  fire event.
- Conflict uses the independent `GPIOInputMonitor` and publishes the two
  states through the existing heartbeat status snapshot. Its monitor is
  disabled by default.
- Linux GPIO access is read-only and is only available through explicit
  construction. The normal HCM controller remains simulated, and no physical
  output path is enabled by these changes.

Physical wiring, electrical conditioning, maintenance-lockout behavior, and
live fire-action commissioning still require a separately approved validation.
This change therefore does not activate monitoring on HCM or Conflict and was
not deployed to either host.
