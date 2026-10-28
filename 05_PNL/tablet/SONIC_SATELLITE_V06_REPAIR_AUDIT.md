# Sonic Satellite v0.6 dashboard repair audit

## Root causes found

1. Lighting rows were discovered by broad `light.*` and `switch.*` scans. The aggregate hidden toggle also targeted the first matching entity, and `All Off` included every configured switch, including `switch.bedroom_camera_power` (the Fan). Brightness was likewise selected through a first-light lookup rather than the approved Glow Lights entity.
2. Action state and polling state shared `requestInFlight`. A successful action immediately started a refresh, while the two-second renderer could rewrite the status during reconciliation. There was no local request identity, and status was stored in the Media Sources card for every controller domain.
3. Media Sources rendered every raw `media_sources` entry without requiring a `media_player` entity, a configured controller, or a `select_media_source` action. That allowed unrelated configuration data to appear as source buttons. The live configuration currently has no media player and no source mappings.

## Corrected client behavior

- Lighting is explicitly ordered and bound to:
  - `light.living_room_glow_all` — Glow Lights, brightness-capable light
  - `switch.lamp_switch` — Lamp
  - `switch.office_lights_switch` — Office Lights
  - `switch.bedroom_camera_power` — Fan
- `All Off` sends individual `turn_off` actions only to configured lighting entities other than Fan. It never sends an area-wide command.
- Climate is limited to `climate.nest_thermostat`; its current temperature, target, HVAC state/action, and supported HVAC modes remain separate from media.
- Media requires an explicitly configured `media_player.*` control. Missing media displays `Media not configured` and leaves controls disabled.
- Media Sources always renders seven slots. A slot is enabled only when Server1 supplies a valid `media_player.*` mapping with a configured `select_media_source` action and source value. No source actions are invented.
- Polling only reads `/panel/config` and `/panel/states`. Only actual click/slider/selector callbacks call `/panel/action`.
- Programmatic state updates are guarded from slider/climate callbacks. Each local action has a unique reconciliation ID; the wire request remains compatible with the deployed Server1 contract.

## Server1 action contract verified

`POST /panel/action` accepts JSON containing `entity_id` and `action`, plus the applicable field: `brightness_pct`, `temperature`, `hvac_mode`, or `fan_mode`. The server validates the configured entity and action, maps it to a fixed Home Assistant service, and returns HTTP 200 with `accepted`, `entity_id`, `action`, and `ha_status`.

No live action request was sent during this repair.

## Verification

- `./gradlew testDebugUnitTest assembleDebug` — passed.
- Python compile and Server1 mock tests — 4 tests passed.
- Live read-only `/panel/config`, `/panel/states`, `/panel/health` — HTTP 200.
- Live config — four requested lighting controls and `climate.nest_thermostat`; no media player; `media_sources: []`.
- Fire 7 install — successful via wireless ADB package-manager install.
- Fire 7 launch — successful; wake engine remained in `Listening` state; no Android crash in captured log.
- Physical screenshot capture is blocked by the app's intentional `FLAG_SECURE`; the captured PNG is black by design. The approved reference image was not present in the project, so pixel-level comparison remains pending.

## Files changed

- `app/src/main/java/com/example/sonicsatilite/PanelController.java`
- `SONIC_SATELLITE_V06_REPAIR_AUDIT.md`

The Server1 source and live services were not modified.
