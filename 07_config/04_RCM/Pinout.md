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

## Bank selection and local overrides

The RCM software samples the front-panel MCP inputs through a nonblocking
250 ms debounce. MCP2 GPA0-GPA3 select banks 1-4 and are active-low; exactly
one stable selector must be asserted. A conflicting selection clears the
software latch and blocks overrides until every selector is released. A
selector asserted during startup is treated as an asserted-at-boot condition
and must be released before a new selection can be accepted.

MCP1 GPA0-GPA7 are Override ON 1-8 and MCP1 GPB0-GPB7 are Override OFF 1-8;
both are active-low. After each accepted bank selection, every override must
first be observed released for the debounce interval. A qualified override is
dispatched once through the existing RCM command and safety path, then waits
for release so a held switch cannot retrigger. The selected bank expires after
5 seconds without a valid selection or dispatched override. Expiry only clears
the software latch; it never changes relay state. The implementation uses
32-bit rollover-safe monotonic milliseconds and exposes latch, conflict,
timeout, generation, and override state in module diagnostics.
