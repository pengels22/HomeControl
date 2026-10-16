# HomeControl Physical Touchscreen Boundary

The ST7796U and FT6336U adapters are derived from the validated
`pengels22/Travel_Laser` implementation at commit
`76cfc35eab04d1f629762a393e66dc1d23979c06`. They are isolated from all
laser, GRBL, K1, USB, and safety-output code. The imported hardware boundary
is selectable, but the HomeControl browser application remains the shared UI
source of truth.

`simulated` is the default and opens no hardware. `orange_pi` is a manual,
commissioning-only mode for `/dev/spidev1.1`, `/dev/i2c-2`, and gpiochip1
lines 70/69. It is not enabled by the preview server and is not invoked by
automated tests.

The browser input bridge is implemented as an optional Linux `uinput` sink in
`input_bridge.py`. It forwards the validated single-contact `down`, `move`,
and `up` lifecycle to the compositor, where the kiosk browser delivers normal
DOM pointer/touch events. Chromium therefore owns hit testing, scrolling,
swipes, pointer capture, and slider interaction; the bridge does not duplicate
the HTML UI or issue HomeControl commands itself.

Install the Linux-only dependency separately on a bench Orange Pi:

```sh
python -m pip install -r 10_scripts/touchscreen_hardware/requirements.txt
```

Then start the existing browser using the command from `browser_bridge.py` and
run the input consumer explicitly, for example:

```sh
./.venv/bin/python 10_scripts/touchscreen_input_bridge.py --role RCM --mode orange_pi
```

The default remains simulated and opens no hardware. The `uinput` device
requires appropriate `/dev/uinput` permissions and compositor acceptance; no
live device-tree, GPIO, SPI, or I2C changes are performed by this repository.
