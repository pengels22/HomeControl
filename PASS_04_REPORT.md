# Pass 4 Report — PNL Firmware and LVGL Contract

Date: 2026-10-24

## Result

Pass 4 adds the bounded dashboard interpreter and deterministic PNL runtime
simulator used to validate the firmware contract. It also adds an ESP-IDF
project scaffold with no GPIO access. The scaffold is intentionally not a claim
that the Waveshare ESP32-P4 display, touch, W5500, BH1750, AHT20, C4002, codec,
microphone, speaker, or power rails are physically validated.

## Implemented software contract

- Five v1 cards are allowlisted: `button`, `slider`, `entity`, `entities`, and
  `thermostat`.
- Layouts are bounded to 1024x600 geometry, eight pages, forty cards, bounded
  text, and no scripts, HTML, arbitrary CSS, or executable expressions.
- Last-good layouts are compiled with a stable SHA and preview mode is marked
  explicitly; preview state cannot execute actions.
- PNL telemetry increments monotonically and includes the four panel-local
  sensor aliases from Pass 3.
- Sonic policy is fail-muted on boot, expired policy, and invalid policy epoch.

## Hardware gate

The ESP-IDF scaffold is build-structured but hardware driver completion remains
blocked on verified manufacturer schematics, ESP-IDF component compatibility,
I/O voltage/rail checks, and an authorized bench session. No physical readiness
is claimed.

## Pass 5 prerequisites

The HCM dashboard backend must consume the same allowlist, geometry, preview
semantics, local aliases, area selectors, and last-good revision behavior before
the browser editor is built.
