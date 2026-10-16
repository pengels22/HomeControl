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

The browser-to-RGB565 deployment approach is intentionally a separate future
integration step: run the existing local UI in a kiosk-capable browser or
WebView on the panel, then connect its local touch bridge to this service.
This keeps HTML/CSS/JavaScript as the UI source and avoids a duplicate,
hard-coded physical UI. No live device-tree, GPIO, SPI, or I2C changes are
performed by this repository change.
