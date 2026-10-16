# Travel Laser Touchscreen Integration

## Scope

The shared touchscreen hardware boundary reuses the validated display and
touch implementation from the local `Travel_Laser` repository at commit
`76cfc35eab04d1f629762a393e66dc1d23979c06`:

- Hosyond ST7796U, 480x320 landscape, RGB565 over `/dev/spidev1.1` at 10 MHz.
- FT6336U polling over `/dev/i2c-2`, address `0x38`.
- LCD D/C: `gpiochip1` line 70 (Orange Pi header pin 11 / PC6).
- Touch reset: `gpiochip1` line 69 (Orange Pi header pin 13 / PC5).
- The LCD reset line is intentionally unmanaged by the software driver.

The source attribution and driver boundary are kept in
`10_scripts/touchscreen_hardware/`. No laser, GRBL, K1, USB, or direct module
control code is included.

## Role profiles

RCM, LCM, and SIM use the Orange Pi profile in their hardware manifests. SIM
LEDs use header pins 15 (LINK / PC8), 16 (STATUS / PC15), and 22 (FAULT /
PC7). LCM Shelly relay assignments are unchanged. HCM retains its separate
Jetson manifest and is not changed by this integration.

The manifests remain the Source of Truth. Physical outputs stay disabled and
the preview defaults to simulated mode. `create_service()` only opens SPI,
I2C, or GPIO nodes when an operator explicitly selects `orange_pi` mode.

## Local diagnostics

Run the non-invasive preview boundary check:

```sh
./.venv/bin/python 10_scripts/touchscreen_hardware/diagnostic.py --role RCM --mode simulated
```

After a separately approved Orange Pi bench setup, the manual hardware check
is:

```sh
./.venv/bin/python 10_scripts/touchscreen_hardware/diagnostic.py --role RCM --mode orange_pi
```

The latter requires `spidev`, `gpiod`, and `smbus2`, Linux device permissions,
the validated SPI1 CS1 device-tree overlay, and the panel wiring to have been
bench-tested. It is not run by the web preview and is not a deployment step.

The overlay source is retained at
`10_scripts/touchscreen_hardware/overlays/spi1-cs1-pins.dts`. Installation,
pinmux changes, and reboot are commissioning actions and must be performed
manually on a test Orange Pi after electrical review; this repository does not
apply them automatically.

## Browser UI boundary

`browser_bridge.py` provides a reproducible 480x320 kiosk command for the
existing role-aware browser UI. `input_bridge.py` provides the corresponding
optional Linux `uinput` consumer. It forwards the Travel_Laser event lifecycle
as a single virtual touch contact:

```text
FT6336U poll -> TouchEventBridge -> uinput down/move/up -> compositor -> Chromium DOM
```

This is the necessary adaptation from Travel_Laser. Travel_Laser consumes the
same events in `_apply_touch()` against its own raster UI, including custom
scroll offsets and delayed button activation. HomeControl does not reproduce
that raster hit-testing layer: the existing HTML/JavaScript UI remains the
source of truth, so Chromium performs native scrolling, swipe recognition,
button activation, slider pointer capture, and release handling. HomeControl's
existing inactivity and command-synchronization JavaScript remains unchanged.

The bridge is still commissioning-only. It is not enabled by the preview
server and is not claimed as physically validated until an Orange Pi confirms
`/dev/uinput` delivery to the selected kiosk compositor.

For the confirmed Travel Laser host, which has no Chromium, compositor, or
framebuffer, `touchscreen_display_bridge.py` uses headless Chromium's CDP
transport. The renderer captures a 480x320 PNG, decodes it to RGB, computes a
changed rectangle, converts that rectangle to big-endian RGB565, and calls the
existing ST7796U driver's partial-window update. Full-frame capture is still
performed because CDP exposes a frame image; the SPI transfer is reduced to the
dirty rectangle. `RenderMetrics` records capture rate, update count, changed
pixels, and capture/update time for the bench report.

The renderer's optional dependencies are Pillow and websocket-client. A
compositor-backed kiosk may instead use the existing `uinput` sink, avoiding
CDP touch injection while retaining the same `TouchEventBridge`.

## Bench workflow

The workflow is deliberately split into non-disruptive preparation and an
explicit handover:

```sh
./.venv/bin/python 10_scripts/travel_laser_bench.py preflight
./.venv/bin/python 10_scripts/travel_laser_bench.py stage
# After physical laser disconnection and operator approval only:
./.venv/bin/python 10_scripts/travel_laser_bench.py test --role RCM --approve-hardware-handover
./.venv/bin/python 10_scripts/travel_laser_bench.py restore
```

The default target is the exact SSH alias `laser`. `preflight` is read-only;
`stage` only copies files into `/tmp` and does not stop services. `test` records
the original Travel Laser service state, stops that service to avoid SPI/I2C
ownership conflicts, and starts only the HomeControl preview plus display
bridge. It cannot prove that a laser is physically disconnected, so that is a
manual gate. `restore` kills only recorded test PIDs, removes the temporary
state, and restores the recorded service enabled/active state. The state file
and restoration commands are designed to remain usable over SSH after a local
development session fails.

## Outstanding verification

No live device, Jetson, LAB1, Conflict service, physical relay, dimmer, or
sensor was modified. Before enabling the physical adapter, verify display
orientation, backlight requirements, touch coordinates, device permissions,
SPI/I2C electrical levels, `/dev/uinput` creation, compositor delivery,
startup behavior, and that browser input is routed only through the existing
authenticated application paths. Exercise taps, release events, vertical
scrolling, swipes, repeated relay presses, and continuous dimmer drags on
each RCM, LCM, and SIM role.
