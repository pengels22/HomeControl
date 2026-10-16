# Shared Touchscreen Implementation

## Preview

The shared local preview is implemented in:

- `10_scripts/touchscreen_app.py`
- `10_scripts/touchscreen_ui/index.html`
- `10_scripts/touchscreen_ui/touchscreen.css`
- `10_scripts/touchscreen_ui/overrides.css`
- `10_scripts/touchscreen_ui/touchscreen.js`

Start it locally with:

```sh
./.venv/bin/python 10_scripts/touchscreen_app.py
```

Open `http://127.0.0.1:8765/?role=RCM` and replace `RCM` with `LCM`, `SIM`,
or `HCM`. The optional `page` query selects a preview page directly, for
example `?role=LCM&page=dimmers`.

The default adapter loads the authoritative module hardware manifest and keeps
all state in memory. It performs no GPIO, SPI, I2C, CAN, Shelly, or live HCM
calls. Simulated acknowledgments explicitly report
`physical_output_commanded: false`.

## Shared behavior

- One router, theme, state model, and adapter boundary serves all four roles.
- Home navigation is capability-based: RCM uses Relays, LCM uses Lights, SIM
  uses RMC Data, and HCM uses Sensors.
- Every title block opens Status; subpages use the shared Back bar.
- Ten seconds of valid-input inactivity returns to Home. Active slider drags
  suppress the timeout until release.
- LCM exposes all 14 dimmers in configuration order. Requested values from 0%
  through 5% normalize to an acknowledged simulated OFF/0% state; 6%-100%
  remain their requested setpoint.
- RCM and LCM relay commands enforce maintenance lockouts and authorization.
- SIM uses `Unavailable` for offline/stale room telemetry.
- HCM Sensors is restricted to external FIRE and AC monitor inputs; internal
  CPU, memory, voltage, network, and remote RMC telemetry are excluded.

## Screenshots

The local capture pass produced 22 PNGs under `tmp/touchscreen-screenshots/`:

- RCM: Home, Status, Relays, Network, Settings
- LCM: Home, Status, Lights, Dimmers, Non-Dimmers, Network, Settings
- SIM: Home, Status, RMC Data, Network, Settings
- HCM: Home, Status, Sensors, Network, Settings

The reproducible capture helper is `10_scripts/screenshot_touchscreen.py`.
It requires the optional Playwright browser tooling and a running local preview.
The reference images are visual guidance; they do not establish the selected
physical display's final pixel resolution or hardware commissioning.

## Hardware boundary

The app is a software preview until the SPI LCD, capacitive touch controller,
Orange Pi/Jetson pinmux, relay hardware, PCA9685 converters, Shelly identities,
and external sensor inputs are separately bench-tested. The existing hardware
manifests remain the Source of Truth and no live device was modified.
