# HCM Type C Jetson front-panel and safety pin map

The authoritative complete inventory is `hardware_pins.yaml`. Physical pins
below are the approved working design and remain `UNVERIFIED` until electrical
commissioning. They are not Linux GPIO line numbers.

| Function | Physical pin | Verification |
|---|---:|---|
| LCD/touch 3.3V | 17 | UNVERIFIED |
| LCD reset | 18 | UNVERIFIED |
| SPI0 MOSI | 19 | UNVERIFIED |
| LCD ground | 20/25 | UNVERIFIED |
| SPI0 MISO reserved | 21 | UNVERIFIED |
| LCD D/C | 22 | UNVERIFIED |
| SPI0 clock | 23 | UNVERIFIED |
| SPI0 CS0 | 24 | UNVERIFIED |
| Touch SDA | 27 | UNVERIFIED |
| Touch SCL | 28 | UNVERIFIED |
| Fault LED | 33 | UNVERIFIED |
| LED ground | 34 | UNVERIFIED |
| Link LED | 35 | UNVERIFIED |
| Status LED | 36 | UNVERIFIED |
| Safety ground | 39 | UNVERIFIED |
| FIRE input | 38 | UNVERIFIED |
| AC-present input | 40 | UNVERIFIED |

FIRE uses the approved NO-to-3.3V, common-to-input, NC-to-ground arrangement:
normal LOW, alarm HIGH, 250 ms software debounce. It remains separate from
ordinary output control. No GPIO overlay or live pin manipulation is performed
by this repository migration.
