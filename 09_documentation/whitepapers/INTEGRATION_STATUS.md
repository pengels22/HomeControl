# HCM Integration Status

This is the reconciliation baseline at the inventory pass ending after
`fcfd1a2e2995b69f318c96afe5c65cdb7e6232e7`. “Software” describes repository
behavior and mocked tests. “Live” is only claimed where this repository records
an actual device/service verification; mocked transports and successful unit
tests do not count as live verification.

## Provider and subsystem matrix

| Provider/subsystem | Software status | Live status | Registration/configuration | Current scope |
|---|---|---|---|---|
| NWS | SOFTWARE_READY | NOT VERIFIED | Factory provider, schema-driven simple form, instance runtime | Forecast, weather sensors, alert lifecycle |
| OpenWeatherMap | SOFTWARE_READY | NOT VERIFIED | Factory provider, encrypted API-key credential, instance runtime | Current weather and forecast |
| OpenAI | SOFTWARE_READY | NOT VERIFIED | Factory provider, encrypted API-key credential, instance service | `openai.generate_text` |
| Google Calendar | SOFTWARE_PARTIAL | NOT VERIFIED | Factory provider, OAuth UI/callback, encrypted token bundle | Calendar state, update/cancel/start/end events |
| Gmail | SOFTWARE_PARTIAL | NOT VERIFIED | Factory provider, OAuth UI/callback, encrypted token bundle | Unread state, History API message events |
| SmartThings | SOFTWARE_PARTIAL | NOT VERIFIED | Factory provider, OAuth, instance webhook route | Discovery, mapped state, switch/level commands, subscriptions |
| Denon AVR | SOFTWARE_PARTIAL | NOT VERIFIED | Factory provider, LAN schema, instance runtime | Main-zone media control over TCP ASCII |
| HEOS | SOFTWARE_PARTIAL | NOT VERIFIED | Factory provider, LAN schema, instance runtime | Player discovery/control over local CLI |
| Native Bluetooth | SOFTWARE_PARTIAL | NOT VERIFIED | Native scanner, authenticated status/discovery APIs | Optional BlueZ/`bleak` observation pipeline |
| iBeacon | SOFTWARE_PARTIAL | NOT VERIFIED | Factory consumer of native scanner, schema-driven config | UUID/major/minor presence and RSSI |
| MQTT bridge | SOFTWARE_PARTIAL | NOT VERIFIED | Native bridge settings, not provider-factory integration | Outbound retained discovery/state plus inbound command path |
| Matter bridge | SOFTWARE_PARTIAL | NOT VERIFIED | Native supervised bridge, not provider-factory integration | HCM channel export and command return path |
| Internal mock | FOUNDATION_ONLY | N/A | Hidden internal provider when configured | Framework registration/lifecycle tests |

No provider is LIVE_VERIFIED by this repository. The deployed host and real
third-party accounts/devices have not been used in CI or this audit.

## Common model inventory

Integration providers register through `provider_factory` when HCM imports the
provider modules during startup. Instance reconstruction is performed by
`integrations.runtime.Runtime.restore_instances`; configured instances receive
an ownership-scoped `Context`. Native MQTT, Matter, and Bluetooth are separate
subsystems and do not pretend to be provider-factory integrations.

The integration entity domains actually used are:

- `weather`: NWS and OpenWeatherMap current/forecast entities.
- `sensor`: temperature, humidity, battery, RSSI, last-seen, mail, appliance,
  and weather counters.
- `binary_sensor`: weather alerts, contact/motion, and iBeacon presence.
- `switch`: SmartThings switch capabilities and MQTT channel projections.
- `light`: SmartThings level capabilities and MQTT lighting projections.
- `device_tracker`: SmartThings presence capability.
- `calendar`: Google Calendar event collection.
- `media_player`: Denon AVR and HEOS.

Entity state is persisted through the generic entity registry and emits the
generic `entity.state_changed` event. Availability is persisted separately and
is now also represented by `entity.availability_changed`. Provider event
payloads include provider and instance metadata through the common event model.

Migration 016 hardens these contracts. Existing entity IDs are retained when
safe; a sibling instance requesting an occupied ID receives a deterministic,
human-readable instance suffix while the immutable database entity ID and room
assignment remain unchanged. Existing owned entities retain their allocated ID
across display-name changes. Service bindings now use instance-aware uniqueness.

## Service inventory

All provider services use the generic service registry, Pydantic argument
schemas, target ownership, and instance-aware handlers. `mutates_physical_state`
is currently false for these integrations because they command external
providers rather than HCM physical outputs.

| Service | Owner | Target |
|---|---|---|
| `openai.generate_text` | OpenAI | none |
| `switch.turn_on`, `switch.turn_off` | SmartThings | SmartThings switch |
| `light.set_level` | SmartThings | SmartThings level entity |
| `media_player.turn_on/off`, `volume_set/up/down`, `mute`, `unmute`, `select_source` | Denon AVR | Denon media entity |
| `media_player.play/pause/stop`, `next`, `previous`, `volume_set/up/down`, `mute`, `unmute`, `play_media` | HEOS | HEOS media entity |
| `notify.send`, `announcement.speak` | HCM Native semantic boundary | Configured destination/backend |
| `internal_mock.ping` | Internal mock | none |

Service declarations are discoverable as semantic names plus eligible instance
bindings. Targeted calls resolve the owning instance from the immutable entity
ID; non-targeted calls require an explicit instance when multiple handlers
exist.

The native notification and announcement services validate bounded semantic
arguments and return `destination_unconfigured` or `backend_unavailable` until
an approved destination/backend is configured. They never send a notification,
generate speech, or contact an external service by themselves. HA mobile notify
targets and TTS media targets therefore remain explicit mapping work in the
compatibility analyzer.

## Event inventory

Generic events include `entity.state_changed` and
`entity.availability_changed`. Provider events currently emitted include:

- `nws.alert_started`, `nws.alert_updated`, `nws.alert_ended`.
- `google_calendar.event_updated`, `event_started`, `event_ended`, and
  `event_cancelled`.
- `gmail.message_received`.
- `smartthings.device_state_changed`, `device_online`, and `device_offline`.
- `ibeacon.entered` and `ibeacon.left`.
- `internal_mock.started`.

Weather poll state and Google/Gmail sync state are durable. Migration 016 adds a
bounded `integration_events` sequence log. Meaningful entity transitions,
availability transitions, and provider lifecycle events are committed before
the in-process bus publishes them; unchanged state writes stay best-effort and
do not create durable rows. Payloads are sanitized, retention is incrementally
capped by seven days, and authenticated consumers can read pages after an event
ID through `GET /api/v1/integrations/events`. Provider deduplication remains
provider-owned. Denon/HEOS external state converges through entity updates,
while iBeacon entered/left transitions are runtime-derived after fresh
observations.

## Provider-specific findings

NWS and OpenWeatherMap share `WeatherState`/`ForecastEntry`, but NWS has less
current-condition detail and uses Fahrenheit-oriented temperature metadata while
OpenWeatherMap follows its configured units. Generic automation should use the
provider field and unit attributes rather than assume one weather payload shape.

Google Calendar has OAuth, selected calendars, normalized timed/all-day events,
event update/cancel and lifecycle scheduling. Recurring occurrence IDs are
preserved by Google item IDs. Gmail has OAuth, baseline suppression, durable
History API cursor/seen IDs, metadata-only message events, and cursor recovery.
Both remain software-partial because no live account verification is recorded.

SmartThings maps switch, level, temperature, humidity, contact, motion,
presence, battery, washer operating/machine state, and dryer operating/machine
state. Unknown capabilities are counted in diagnostics. Level is exposed as a
`light` entity; washer/dryer entities are read-only. Device availability is
mapped, but provider-specific capability values remain partly provider-shaped.

Denon and HEOS use common media field names (`state`, `power`,
`volume_level`, `muted`, `source`, `source_list`, and metadata where available)
but need live protocol verification. Denon secondary zones and HEOS group
commands are deferred.

Bluetooth has exactly one scanner path per configured scanner instance; iBeacon
subscribes to it and does not create another scanner. Generic observations are
bounded and expiring; configured beacons alone create persistent HCM devices.
The Linux backend requires BlueZ/D-Bus host access and an installed `bleak`
package; no such dependency or container capability is currently declared.

MQTT is an HCM channel bridge using `aiomqtt`, environment/settings-based broker
configuration, TLS support, retained Home Assistant discovery, outbound state,
and inbound revalidated commands. It is not an instance/provider registry
integration and has no external-device discovery model. Matter is an optional
supervised Node bridge exporting HCM lighting channels with persistent endpoint
allocation; it is not a Matter controller and does not import/commission
external Matter devices. Both have software tests but no live broker/fabric
acceptance in this repository.

## Security and authorization

Credential values are encrypted through the integration credential store. OAuth
tokens are stored as encrypted bundles with metadata; API keys are passed to
provider clients but are not returned by inspection or diagnostics. No source
or frontend file contains live credentials. The unused SmartThings webhook-secret
configuration field was removed during this audit rather than storing a secret
in normal configuration JSON.

Integration mutation endpoints enforce ADMIN on the backend. Authenticated
READONLY users can inspect integrations, devices, entities, services, status,
and diagnostics. Service invocation enforces provider/instance availability,
target ownership, target domain, and schema validation. No public generic
provider-control proxy was found.

## Startup and task review

Provider modules are imported during HCM lifespan, registered, then instances
are restored. Disabled instances are not started; unknown providers become
`provider_missing`; failures are isolated to the instance. Background work is
owned by provider instances and generally cancelled by `stop_instance` or HCM
shutdown: weather/Google/Gmail/SmartThings polling, Denon/HEOS reconnect loops,
Google calendar lifecycle tasks, OAuth refresh tasks, and iBeacon timeout tasks.
The native Bluetooth scanner is started/stopped by HCM lifespan.

Remaining task risks are bounded but should be addressed before automation: BLE
advertisement callbacks create untracked asyncio tasks, and durable service
definitions do not distinguish same-named instance services.

## Frontend and Automation readiness

The generic Settings integration page supports provider cards, schema-driven add
forms, credentials, OAuth connect flows for Google/SmartThings, enable/disable,
reload, remove, device/entity counts, and authenticated inspection APIs. There
is no dedicated Bluetooth discovery adoption workflow and no provider-specific
media/weather editor. Devices and entities are available through generic API
views; no separate SmartThings/Denon/Bluetooth database exists.

The integration layer now exposes the generic substrate Automation needs:
immutable database entity IDs, collision-safe entity IDs, instance-aware service
bindings and target routing, sanitized durable event cursors, current state,
availability, and provider events. Automation can consume these interfaces
without provider-specific knowledge. Durable event cursor ownership is now implemented by the Automation Engine V1; see [Automation Engine V1](AUTOMATION_ENGINE.md). Provider-specific automation policy remains outside the integration layer.

## Deferred scope

No cameras, ONVIF, Scrypted, WebRTC, UniFi Protect, HomeKit Bridge, ZHA,
ESPHome, OctoPrint, Traeger WiFIRE, AdGuard, network scanner, Mail and
Packages, HACS, HA Supervisor, Node-RED Companion, or HA Scheduler integration
is implemented. Matter remains the preferred future Apple ecosystem bridge.

## Live validation backlog

Perform only with explicit credentials/devices and normal deployment safeguards:

1. NWS request and alert delivery from the deployed HCM host.
2. OpenWeatherMap API-key request and unit/forecast validation.
3. OpenAI request timeout, redaction, and service authorization.
4. Google OAuth, Calendar lifecycle, Gmail History cursor and privacy checks.
5. SmartThings washer/dryer discovery, webhook signature, subscription, and
   command/state echo checks.
6. Denon AVR power/volume/source and receiver reboot recovery.
7. HEOS player discovery, metadata, playback, and reconnect behavior.
8. Linux BlueZ/`bleak` adapter access and physical iBeacon enter/leave behavior.
9. MQTT broker TLS/authentication, retained discovery, and command rejection.
10. Matter bridge startup, persistent storage, pairing/fabric, and command path.

The current classification is **INTEGRATION_LAYER_READY_FOR_AUTOMATION**. No
deployment or live credential testing was performed in this audit; provider live
verification statuses remain unchanged.
