# 21-inch monitor — backend wiring acceptance checklist

Status: **PARTIALLY WIRED**. The kiosk backend is authenticated to Home Assistant. Thermostat controls use the explicit `climate.nest_thermostat` allowlist and Alarmo controls use `alarm_control_panel.alarmo`; lighting remains preview-only and Calendar/Media remain unavailable.

## Source of truth
- HCM entity registry and room assignments in PostgreSQL own the logical entity IDs.
- Inspect live deployment and existing authentication/API/event contracts; never guess addresses, tokens, entity IDs, API paths, or device capability.
- HA may be a device provider if actually integrated. A compatibility importer alone does not provide a live control path.
- No browser-embedded HA long-lived tokens or HCM admin credentials. No direct browser->module controls.
- Never silently change HVAC safety sequencing, fire/lockout protections, RCM mapping or alarm authorization.

## Required implementation order
1. Inventory deployed HCM entities and authorized API paths, backend connectivity from HAMonitor, currently configured HA providers, and screen's actual origin. Record friendly name, immutable ID, type, area, capability, state, availability, service and verification status.
2. Implement a local authenticated API/session bridge **only if required**, served same-origin to the monitor; limited to allowlisted read-only entity discovery + subscription and capability-checked control commands. Use existing backend if already available; avoid parallel unauthorized registry. Use timeouts, CSRF protections, request auditing (without secrets/PINs), explicit origin/access restrictions, reconnect/backoff.
3. Add a frontend entity-client abstraction: load entities on startup; subscribe to state and availability events; reconnect with bounded backoff and snapshot resync; show connected/stale/unavailable/pending/error accurately. Treat backend state as authoritative; never optimistically show a command as complete.
4. Map each existing room/light button to an actual discovered entity and supported service. Map zone intensity/color to confirmed brightness/RGB attributes. If any entity cannot be uniquely matched, leave that control disabled with its unresolved ID documented. Keep `approved_trace.svg` byte-for-byte unchanged.
5. Climate: use the authenticated thermostat entity, with allowlisted modes and bounded setpoint actions; preserve HCM/HA safety ownership.
6. Calendar: connect to the actual authorized calendar provider, implementing read/list before write.
7. Media: map sources and controls to verified Denon/HEOS or other supported services; no fictional source commands.
8. Alarm: use only the server-side authenticated Alarmo allowlist; never keep an alarm PIN or token in localStorage or logs.
9. Timers: identify and integrate a real persisted service or label timers strictly local.
10. Test Pi 2B Chromium rendering/performance, actions, stale behavior, browser refresh/restart recovery, and rollback. Deploy to Pi only with explicit approval under AGENTS.md.

## Required entity audit output

Create `ENTITY_WIRING_AUDIT.md` with rows:
page | UI control | physical device/provider | HCM logical/immutable entity ID | available services | read test | command/ACK test | status | blocker.

Do not fabricate values. A blank/unresolved field is safer than a wrong mapping.

## Deployment acceptance
- Every enabled control reads a real state and receives verified acknowledgement.
- Disconnected UI safely disables actions, without displaying preview state as live.
- Tests do not change life-safety outputs or thermostat hardware unexpectedly.
- Live test report specifies what device changed, which command and ACK were observed, and how restored.
- No backend API exposed to unauthenticated WAN/browser origins.
