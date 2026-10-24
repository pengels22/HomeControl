# Pass 7 hardware blockers

- ESP32-P4 board bring-up, boot storage, watchdog, and native LVGL rendering.
- W5500 link negotiation, Ethernet identity selection, TLS transport, and cable/power behavior.
- Actual lux, occupancy, temperature, and humidity sensor wiring, calibration, and invalid-reading behavior.
- Touchscreen dimensions, touch controller, brightness, and enclosure/power validation.
- Physical microphone capture, mute enforcement, speaker/audio transport, and SVR1 network path.
- Relay or thermostat output electrical validation and safe-state behavior.

The simulator and compiler tests intentionally do not promote any of these to
hardware readiness.
