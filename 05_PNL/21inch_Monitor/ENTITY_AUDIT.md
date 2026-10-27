# 21-inch Monitor entity and integration audit

This audit describes what the dashboard can currently prove. It is intentionally conservative: a control is not presented as live unless an authenticated backend mapping has been verified.

## Current implementation

| Area | Current state | Source / mapping | Physical command? |
|---|---|---|---|
| Rooms | Available as the approved static trace with touch polygons | `static_apartment_config.js` | No |
| Room lighting | Preview-only toggles and animated SVG zones | `preview.*` identifiers in `static_apartment_config.js` | No |
| Climate | Unavailable state with disabled controls | No authenticated monitor session or verified entity mapping | No |
| Calendar | Unavailable state; no fictional events | No authenticated calendar provider configured for this kiosk | No |
| Cooking | Local preview timers; browser-memory only | `window._timers` | No |
| Media | Disabled | No authenticated, monitor-safe provider mapping | No |
| Alarmo | Disabled, including PIN keypad | No authenticated server-side alarm integration | No |

## Safety boundaries

- No Home Assistant token, password, or permanent credential is stored in frontend code.
- No browser control calls a physical module directly.
- Preview lighting is labeled and is not authoritative device state.
- Climate, calendar, media, and alarm commands remain disabled until their authenticated HCM integrations and entity mappings are tested.
- Local cooking timers are not persistent and are not represented as an external kitchen integration.

## Required next integration work

The monitor needs a server-side authenticated bridge that exposes only the approved logical entities and returns explicit `live`, `stale`, `unknown`, or `unavailable` states. Once that bridge exists, mappings should be added here and covered by focused tests before enabling any command buttons.
