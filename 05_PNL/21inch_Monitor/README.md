# 21-inch Monitor — Apartment Dashboard Prototype

This folder is deliberately isolated from the 7-inch ESP32 PNL firmware. It targets an existing Raspberry Pi-driven 21-inch touch display and is intended to become a Chromium kiosk web frontend.

## Current state

- `index.html` is a standalone, dependency-free HTML/CSS/SVG/JavaScript prototype.
- Approximate rooms and sample furniture match the user's hand-sketched floor plan at a conceptual level; dimensions, doors, fixtures and furniture positions have **not** been surveyed.
- Tapping a room shows example lighting controls; toggles modify **browser-memory preview state only**. No command is sent to any physical device.
- Top/tilt switches between flat and skewed SVG views. This is **not true 3D**.
- Timers count down locally while the page is open.
- Media and alarm controls are disabled until authenticated integrations are designed.
- Climate, calendar and cooking navigation entries are placeholders.
- No HCM or HA credentials, tokens, or network endpoints are stored in the frontend.

## Run the preview

From the repository root:

```sh
python3 -m http.server 8765 --directory 05_PNL/21inch_Monitor
```

Open `http://localhost:8765` in a browser, or use the machine's LAN address when appropriate. Stop with Ctrl+C. This is an **unencrypted development preview server**; do not expose it to the internet or use it for live home controls.

## Codex implementation handoff

1. Keep all 21-inch code under `05_PNL/21inch_Monitor/`. Do not modify 7-inch PNL native LVGL firmware merely to support this display.
2. Before backend integration, inspect root `AGENTS.md`, `README.md`, the white-paper index, relevant security/runbooks and existing HCM API contracts. HCM remains authoritative for logical control mappings and safety.
3. Replace the approximate SVG with an **actual furnished 3D apartment model**, ideally rendering with a performant WebGL engine and a fallback for Pi devices without adequate GPU performance. Use the user-supplied hand sketch as geometry reference. Do not claim a proper 3D implementation until there is navigable geometry and real lighting effects.
4. Store room polygons/model object IDs and logical light identifiers in a dedicated editable configuration file, not embedded throughout rendering code.
5. Provide responsive controls suitable for the measured native resolution of the 21-inch display. Verify on the actual target browser and hardware, checking frame rate, memory and touch selection accuracy.
6. Implement device-state subscriptions and commands **through an authorized backend**, not browser-exposed permanent HA tokens, direct module transport, or hardcoded secrets. Confirm actual authenticated HCM APIs and HA integration requirements before wiring controls.
7. Distinguish live, stale, unknown, unavailable and preview device states. Never make a preview appear to be authoritative device state.
8. Alarm disarm/arming requires secure server-side handling, explicit error/ack state and no PIN persistence or logging. Do not auto-enable existing placeholders.
9. Add tests for room-device mapping, model selection, no-unsafe-controls when disconnected, and timer lifecycle. Validate accessibility and keyboard fallback.
10. Follow AGENTS.md for focused tests and required final validation; never assert hardware tests were performed unless actually performed.

## Intended layout

- Full-height narrow navigation column at left.
- Main centerpiece is the interactive apartment floorplan; room taps select the associated lighting controls.
- Right vertical rail holds selected-room controls, media, Alarmo keypad area, and quick timers.
- Later pages can include Calendar, Cooking, Climate, weather and other dashboards.

## Safety boundaries

This prototype intentionally cannot switch physical relays or disarm security systems. Those actions require a deliberate, authenticated integration phase and appropriate tests.
