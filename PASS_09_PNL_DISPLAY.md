# Pass 9 PNL display

The shared `05_PNL/display_engine.py` is the native-style display model for the
desktop preview and future LVGL adapter. It consumes the Pass 4 declarative
layout schema, preserves a last-good compiled layout, renders a full-width
1024×600 frame, resolves `local.*` directly from panel state, and disables
remote actions when HCM is unavailable.

The launchable desktop preview is `python -m 05_PNL.desktop_simulator` and is
served at `http://127.0.0.1:8765`. Its HTML is a review surface only; geometry,
state availability, local alias resolution, and fallback behavior are covered by
the Python display engine tests. It has no permanent sidebar and no Scenes
section.

The ESP-IDF scaffold remains hardware-gated. No Waveshare pin map, W5500
configuration, sensor driver, microphone codec, or LVGL electrical readiness is
claimed without the board and authoritative schematic validation.
