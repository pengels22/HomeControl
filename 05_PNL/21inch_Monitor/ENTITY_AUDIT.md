# 21-inch Monitor entity and integration audit

This audit describes the dashboard's safety boundaries. The live registry inventory and unresolved mappings are recorded in [ENTITY_WIRING_AUDIT.md](ENTITY_WIRING_AUDIT.md). A control is not presented as live unless an authenticated backend mapping has been verified.

## Current implementation

| Area | Current state | Source / mapping | Physical command? |
|---|---|---|---|
| Rooms | Available as the approved static trace with touch polygons | `static_apartment_config.js` | No |
| Room lighting | Preview-only toggles and animated SVG zones | `preview.*` identifiers in `static_apartment_config.js` | No |
| Climate | Live mode and setpoint controls | Authenticated HA bridge, `climate.nest_thermostat` | Yes, allowlisted and range-checked |
| Calendar | Unavailable state; no fictional events | No authenticated calendar provider configured for this kiosk | No |
| Cooking | Local preview timers; browser-memory only | `window._timers` | No |
| Media | Disabled | No authenticated, monitor-safe provider mapping | No |
| Alarmo | Live arm/disarm controls with transient keypad | Authenticated HA bridge, `alarm_control_panel.alarmo` | Yes, allowlisted; PIN is never persisted or logged |

## Safety boundaries

- No Home Assistant token, password, or permanent credential is stored in frontend code.
- No browser control calls a physical module directly.
- Preview lighting is labeled and is not authoritative device state.
- Calendar and media commands remain disabled until their authenticated integrations and entity mappings are tested.
- Thermostat and Alarmo commands use only the server-side allowlist; the browser never receives the HA token.
- Local cooking timers are not persistent and are not represented as an external kitchen integration.

## Required next integration work

The monitor needs a server-side authenticated bridge that exposes only the approved logical entities and returns explicit `live`, `stale`, `unknown`, or `unavailable` states. Once that bridge exists, mappings should be added here and covered by focused tests before enabling any command buttons.
