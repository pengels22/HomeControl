# Approved static layout — 21-inch monitor

The user approved the architectural trace and lights-off/on overlays. The apartment geometry is therefore **LOCKED**. Use `approved_trace.svg` as the rendered base: blue = full-height wall, orange = pony wall. **Do not regenerate the floor plan** using a generative image model, and do not alter wall coordinates when adding effects or controls.

The existing `index.html` loads `approved_trace.svg` (rather than WebGL or the former illustrative plan) and uses `static_apartment_config.js` for approximate touchscreen hotspots and preview lighting zones. The base SVG and overlay SVG share `viewBox="110 130 1250 720"`, so scaling both to the same stage keeps coordinates aligned. Dashboard sidebar controls are distinct from apartment rooms. Entry is outside the apartment.

## Local visual preview
From the repository root, run:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory 05_PNL/21inch_Monitor
```

Open http://127.0.0.1:8765/ ; preview toggles can be tested by selecting a room. No HA/HCM backend commands are sent. Alarm and media control are intentionally unavailable. Local timers are not persistent.

## Target Pi deployment handoff (Codex)
1. Checkout `21inch_Monitor`, read repo AGENTS.md and relevant deployment instructions.
2. Identify the existing Raspberry Pi/kiosk installation from SSH config. Do not guess host, user, display resolution or service name.
3. Back up the deployed dashboard and kiosk startup configuration before changing anything.
4. Deploy this static folder via the **existing** web service and kiosk arrangement; do not create another competing kiosk startup.
5. Verify the Pi actually loads `approved_trace.svg`, `static_apartment_config.js`, and `static_apartment.js` (HTTP 200; no browser errors or network dependencies).
6. Compare actual screenshot to approved trace, check scaling and alignment; test room touch selection, sample light preview, and timer buttons.
7. Leave HA/HCM integration unconnected until authenticated APIs and mapping are independently tested; do not deploy secrets to browser.
8. Record deployed revision, test evidence and rollback procedure. Restore immediately if viewport rendering or startup fails.

The current visual preview has not been verified on the physical Pi by ChatGPT.
