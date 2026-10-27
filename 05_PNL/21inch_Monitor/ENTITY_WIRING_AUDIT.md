# 21-inch Monitor entity wiring audit

Observed from the live HCM PostgreSQL registry on 2026-10-27. This is an
inventory report, not a claim that the monitor is wired. No database rows were
changed and no physical command was sent.

## Live registry summary

| Registry area | Observed result | Status |
|---|---|---|
| HCM API | `192.168.20.27:8080` responds; protected registry routes return `401` without a session | Reachable, authenticated monitor session missing |
| HCM native provider | `hcm_native`, enabled/configured/connected | Live provider |
| Rooms | 0 rows in `rooms` | No room assignment source |
| Light entities | 0 entities with a light or dimmable-light capability | Living Room light cannot be uniquely mapped |
| Touchscreen devices | 0 registered devices and 0 sessions | No approved monitor authentication path |
| External providers | Google Calendar, HEOS, Denon, SmartThings, weather, and others disabled; HEOS instance is `provider_missing` | Unavailable |

## Entity mapping

| Page | UI control | Physical device/provider | HCM logical/immutable entity ID | Available services | Read test | Command/ACK test | Status | Blocker |
|---|---|---|---|---|---|---|---|---|
| Rooms | All Living Room lights | None discovered | Unresolved | None | Registry contains no light entity | Not attempted | **Unavailable** | No light entity, room, or monitor session |
| Rooms | All other room lights | None discovered | Unresolved | None | Registry contains no light entities | Not attempted | **Unavailable** | No verified mapping |
| Climate | Thermostat state | HCM Native | `climate.hcm_hvac` | `climate.set_hvac_mode`, `climate.set_temperature`, `climate.turn_off` | **Pass**: available state observed; mode `off`, setpoint `70°F` | Not attempted | **Read available / control disabled** | No monitor session; command would change HVAC state |
| Calendar | Calendar events | Google Calendar | Unresolved | None | **Fail**: provider disabled/unconfigured | Not attempted | **Unavailable** | OAuth provider not configured |
| Media | Living Room player | HEOS | `media_player.player__1939336346` | Provider service path not available | **Fail**: entity is unavailable/disabled | Not attempted | **Unavailable** | HEOS instance `provider_missing` |
| Cooking | Local timer presets/custom timer | Browser-local timer | None | Local `start`/`cancel` only | **Pass**: local preview behavior | Not applicable | **Local preview** | Not persisted or backend-backed |
| Alarm | Arm/disarm/PIN | None discovered | Unresolved | None | **Fail**: no authenticated Alarmo provider | Not attempted | **Unavailable** | Server-side alarm integration absent |

## Observed HCM entities

| Entity | Provider | Available | State/attributes summary |
|---|---|---:|---|
| `climate.hcm_hvac` | `hcm_native` | yes | `off`; requested/effective `70°F`; modes `off`, `heat`, `cool`, `fan`; current temperature `null` |
| `input_button.volume_up` | `hcm_native` | yes in entity table, logical device unavailable | No state; no useful monitor mapping |
| `media_player.player__1939336346` | `heos` | no | Living Room player; HEOS provider disabled and instance `provider_missing` |

## Why the Living Room light cannot be connected yet

The approved floor-plan configuration currently contains preview identifiers
such as `preview.living.lamp`, but the live registry has no corresponding
logical device, channel entity, room assignment, or authenticated touchscreen
session. Those preview identifiers are not safe substitutes for HCM IDs, so
the monitor remains fail-closed and no switch command was issued.

## Required backend prerequisites

1. Register/import the actual lighting logical devices and assign them to HCM
   rooms, with state/capability metadata.
2. Provision an approved touchscreen device/session with at least the intended
   monitor permission; no such device currently exists.
3. Verify the HCM API read/subscription contract for the monitor. The current
   authenticated integration API exposes registry inspection and durable event
   reads, but there is no unauthenticated or browser-safe monitor bridge.
4. After a unique Living Room light is present, perform a supervised on/off
   test and record the backend acknowledgement before enabling its UI control.

No credentials, token hashes, PINs, or provider configuration payloads are
included in this report.
