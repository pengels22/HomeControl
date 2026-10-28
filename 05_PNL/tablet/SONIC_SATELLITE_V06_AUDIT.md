# Sonic Satellite v0.6 audit and checkpoint

Audit date: 2026-10-25

## Baseline checkpoint

The Android baseline is commit `18aa4d5` (`first commit`). A new Git index/commit could not be created in this environment because the repository metadata at `/Users/patrickengels/.git` is read-only. No live Server1 changes were made.

## Findings

- `MainActivity` owns the dashboard and the existing Jarvis audio state machine.
- `SonicApi` previously exposed only `/health`, `/mic-policy`, and `/voice-command`.
- The four dashboard cards were static placeholder XML; no touch controls existed.
- Microphone capture uses a single-thread executor and network work uses a separate fixed pool. The v0.6 panel client must remain on the network pool.
- The only entity explicitly verified by the project brief is `light.living_room_glow_all`. Local HA automation exports contain other candidates, but they are not treated as verified panel assignments.
- The local Server1 bridge package implements `/voice-command` only. It has no `/panel/*` implementation.

## Confirmed Living Room validation

On 2026-10-25, a read-only authenticated query from Server1 to Home Assistant returned all five user-confirmed entities:

- `light.living_room_glow_all` — `off`
- `switch.lamp_switch` — `off`
- `switch.office_lights_switch` — `off`
- `switch.bedroom_camera_power` — `off` (mapped only as the dashboard Fan control)
- `climate.nest_thermostat` — `heat`, current `70`, target `69`, modes `off`, `heat`, `cool`, `heat_cool`

No thermostat or media action was sent. The authenticated public `GET /panel/config` route still returns HTTP 404 because the additive Server1 panel API has not been deployed.

## Safe scope

The Android client uses only server-authoritative `/panel/config` and `/panel/states` data. It does not invent climate, media, switch, or source entity IDs. Touch actions are sent only for entities/actions received in the panel configuration. Until Server1 exposes the contract, the panel remains unavailable and does not issue device commands.

