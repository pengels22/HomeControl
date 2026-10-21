# RCM Type A pin and output map

The authoritative complete inventory is `hardware_pins.yaml`. All physical
assignments are `UNVERIFIED`; this file documents the active design only and
does not enable relay writes.

| Relay range | Controller | Index range |
|---|---|---:|
| A1-A8 | XL9535 relay card 1 at 0x20 | 0-7 |
| B1-B8 | XL9535 relay card 1 at 0x20 | 8-15 |
| C1-C8 | XL9535 relay card 2 at 0x21 | 0-7 |
| D1-D8 | XL9535 relay card 2 at 0x21 | 8-15 |

| Faceplate function | Controller | Mapping |
|---|---|---|
| Override ON | MCP1 at 0x26 | GPA0-GPA7 |
| Override OFF | MCP1 at 0x26 | GPB0-GPB7 |
| Bank selection | MCP2 at 0x27 | GPA0-GPA3 |
| LEDs / remaining faceplate I/O | MCP2 at 0x27 | Explicitly documented in manifest |

The RCM has 32 logical relay channels, named A1 through D8. Shared commons,
Phoenix terminal positions, active polarity, current capacity, and boot-state
behavior require physical validation and are not inferred here.
