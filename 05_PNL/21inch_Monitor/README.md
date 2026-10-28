# 21-inch Monitor — Apartment Dashboard Prototype

This folder is deliberately isolated from the 7-inch ESP32 PNL firmware. It targets an existing Raspberry Pi-driven 21-inch touch display and is intended to become a Chromium kiosk web frontend.

## Current state

- `index.html` is a standalone, dependency-free HTML/CSS/JavaScript frontend.
- `approved_trace.svg` is the approved local apartment floor-plan asset. It is loaded unchanged as the background; the old `apartment_render.svg` is retained only as a historical artifact and is not loaded.
- `static_apartment_config.js` contains editable room polygons, independent lighting zones, preview entities, and mask colors.
- `static_apartment.js` builds the SVG hit-zone and animated lighting overlay without WebGL, Three.js, or network-loaded libraries.
- The main room view uses the supplied DXF-derived 2D plan, and the 3D selector uses the user-supplied desktop model screenshot at `assets/architectural/apartment-3d-user.png`.
- `assets/architectural/2160_Sandy_Shore_3D_model.glb`, the IFC, and DXF are retained as architectural references. `ARCHITECTURAL_VALIDATION.md` records the IFC checks and the current 3D projection limitation.
- Tapping a room selects it and updates the contextual light controls. Toggle state is explicitly **Preview** state held in browser memory; no physical command is sent.
- The fixed plan is deliberately static; room selection and lighting visualization are separate editable overlays.
- Timers count down locally while the page is open and are labeled as local preview timers.
- The thermostat page provides live mode and setpoint controls for `climate.nest_thermostat` through the authenticated backend.
- Alarmo provides live arm-home, arm-away, arm-vacation, and disarm controls for `alarm_control_panel.alarmo`; any PIN is keypad-only, transient, and never persisted or logged.
- Media and Calendar remain unavailable until their authenticated integrations are verified. Cooking provides clearly labeled Home Assistant timer controls.
- `ENTITY_AUDIT.md` records the current entity/provider mapping and every intentionally disabled control.
- No HCM or HA credentials, tokens, or network endpoints are stored in the frontend.

### Raspberry Pi rendering note

The current target is a Raspberry Pi 2B. Both the SVG plan and the optional 3D
view use pre-rendered/static assets; the Pi does not continuously render the GLB.

## Run the preview

From the repository root:

```sh
python3 -m http.server 8765 --directory 05_PNL/21inch_Monitor
```

Open `http://localhost:8765` in a browser, or use the machine's LAN address when appropriate. Stop with Ctrl+C. This is an **unencrypted development preview server**; do not expose it to the internet or use it for live home controls.

## Codex implementation handoff

1. Keep all 21-inch code under `05_PNL/21inch_Monitor/`. Do not modify 7-inch PNL native LVGL firmware merely to support this display.
2. Before backend integration, inspect root `AGENTS.md`, `README.md`, the white-paper index, relevant security/runbooks and existing HCM API contracts. HCM remains authoritative for logical control mappings and safety.
3. The current frontend provides a static furnished rendering. Continue refining the editable SVG and masks from `APARTMENT_LAYOUT.md`; do not treat the rough sketch as a measured survey.
4. Store room polygons/model object IDs and logical light identifiers in a dedicated editable configuration file, not embedded throughout rendering code.
5. Provide responsive controls suitable for the measured native resolution of the 21-inch display. Verify on the actual target browser and hardware, checking frame rate, memory and touch selection accuracy.
6. Implement device-state subscriptions and commands **through an authorized backend**, not browser-exposed permanent HA tokens, direct module transport, or hardcoded secrets. Confirm actual authenticated HCM APIs and HA integration requirements before wiring controls.
7. Distinguish live, stale, unknown, unavailable and preview device states. Never make a preview appear to be authoritative device state.
8. Alarm disarm/arming uses the server-side Alarmo allowlist, explicit error/ack state and no PIN persistence or logging.
9. Add tests for room-device mapping, model selection, no-unsafe-controls when disconnected, and timer lifecycle. Validate accessibility and keyboard fallback.
10. Follow AGENTS.md for focused tests and required final validation; never assert hardware tests were performed unless actually performed.

## Intended layout

- Full-height narrow navigation column at left.
- Main centerpiece is the static furnished apartment plan; room taps select the associated lighting controls.
- Right vertical rail holds selected-room controls, media, Alarmo keypad area, and quick timers.
- Later pages can include Calendar, Cooking, Climate, weather and other dashboards.

## Safety boundaries

Lighting remains preview-only. Thermostat and Alarmo commands require the authenticated local backend and are limited to the explicitly allowlisted entities and services.
