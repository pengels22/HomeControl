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
existing role-aware browser UI. The browser remains the UI source of truth;
there is no duplicate native relay/dimmer interface. A production panel still
needs a separately tested browser/WebView input bridge that forwards FT6336U
touch events to browser pointer events. That bridge is intentionally not
enabled until the panel, pinmux, permissions, and touch coordinate transform
are bench-verified.

## Outstanding verification

No live device, Jetson, LAB1, Conflict service, physical relay, dimmer, or
sensor was modified. Before enabling the physical adapter, verify display
orientation, backlight requirements, touch coordinates, device permissions,
SPI/I2C electrical levels, startup behavior, and that browser input is routed
only through the existing authenticated application paths.
