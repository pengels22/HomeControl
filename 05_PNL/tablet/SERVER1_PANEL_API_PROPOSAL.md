# Server1 dashboard API proposal

This is a review artifact, not a deployment. It does not modify Server1.

All routes are behind the existing Caddy HTTPS listener and dedicated Fire 7 bearer credential. The server must authorize a panel capability such as `dashboard.read` / `dashboard.control` before processing a request. HA credentials remain server-side.

## `GET /panel/config`

```json
{
  "panel_id": "fire7-living-room",
  "revision": 1,
  "updated_at": "2026-10-25T00:00:00Z",
  "controls": [
    {"entity_id":"light.living_room_glow_all","type":"light","label":"Glow Lights","order":10,"actions":["turn_on","turn_off","set_brightness"]},
    {"entity_id":"switch.lamp_switch","type":"switch","label":"Lamp","order":20,"actions":["turn_on","turn_off"]},
    {"entity_id":"switch.office_lights_switch","type":"switch","label":"Office Lights","order":30,"actions":["turn_on","turn_off"]},
    {"entity_id":"switch.bedroom_camera_power","type":"switch","label":"Fan","order":40,"actions":["turn_on","turn_off"]},
    {"entity_id":"climate.nest_thermostat","type":"climate","label":"Nest Thermostat","order":50,"actions":["set_temperature","set_hvac_mode","set_fan_mode"]}
  ],
  "media_sources": []
}
```

Only server-configured entities and safe action names are returned. No HA token or unrestricted service name is returned.

## `GET /panel/states`

```json
{
  "snapshot_at":"2026-10-25T00:00:02Z",
  "states":[
    {"entity_id":"light.living_room_glow_all","state":"on","available":true,"attributes":{"brightness":97},"last_changed":"2026-10-25T00:00:01Z","last_updated":"2026-10-25T00:00:01Z"}
  ]
}
```

The server batches exactly the configured entities and returns meaningful `503`/`502` errors when HA cannot be read. HA state is authoritative; an accepted action is not confirmation of physical state.

## `POST /panel/action`

Accepted body examples are `{ "entity_id":"...", "action":"turn_on" }` and `{ "entity_id":"...", "action":"set_brightness", "brightness_pct":38 }`. The server validates JSON size, entity membership, action membership, numeric ranges, and rate limits, then maps the action to fixed HA service calls. It must reject client-supplied service domains, service names, target entities, scripts, and arbitrary commands.

Suggested bounded action set: `turn_on`, `turn_off`, `set_brightness`, `set_temperature`, `set_hvac_mode`, `set_fan_mode`, `media_play_pause`, `media_next_track`, `media_previous_track`, `volume_set`, and `select_media_source`.

## `GET /panel/health`

Returns authenticated panel capability and upstream status, for example `{ "ok":true, "ha":"reachable", "config_revision":1 }`. It must not report healthy when HA is unavailable.

## Configuration updates

For the manual editor, add `PUT /panel/config` with server-side validation and revision/ETag conflict handling. The tablet may submit labels, order, control type, and fixed source mapping identifiers only; it may not submit arbitrary HA service calls or credentials. A separate `POST /panel/validate-entity` can validate an entity against HA before saving, but the saved panel remains the server source of truth.

