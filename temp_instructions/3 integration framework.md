Repository:
pengels22/HomeControl

Branch:
main

Starting SHA:
<LATEST_SHA>

==================================================
HCM THIRD-PARTY INTEGRATION FRAMEWORK
MASTER IMPLEMENTATION SPECIFICATION
==================================================

IMPORTANT

Read and follow AGENTS.md before changing anything.

This pass is NOT a request to recreate Home Assistant's entire integration
ecosystem.

The goal is to create a clean, extensible HCM integration framework and then
implement only the integration families currently approved for HCM.

Follow the repository's efficient test policy:

During development:
- use focused tests
- avoid repeated full pytest runs
- avoid repeated whole-repo rescans
- inspect only relevant code once identified

At completion:
- full pytest once
- focused fixes if needed
- one final full pytest rerun only if necessary
- compileall once
- JavaScript syntax once
- git diff --check once
- migration/config validation once
- hosted CI exact SHA

==================================================
1 — PRIMARY GOAL
==================================================

Create an HCM-native third-party integration framework.

Third-party systems must plug into generic HCM registries rather than modifying
the core automation engine or hardcoding provider-specific behavior throughout
the application.

Target architecture:

External service / protocol
        ↓
HCM Integration Provider
        ↓
Device / Entity / Service / Event registries
        ↓
HCM core
        ↓
Automations / UI / companion app / other consumers

The Automation Engine must consume normalized HCM entities, services, states
and events.

It must NOT need provider-specific knowledge.

==================================================
2 — CURRENT EXTERNAL INTEGRATION ROADMAP
==================================================

Approved current external integration families:

1. Google Calendar
2. Gmail
3. Matter
4. MQTT
5. National Weather Service
6. OpenAI
7. OpenWeatherMap
8. Denon AVR
9. HEOS
10. SmartThings
11. iBeacon support through HCM Bluetooth
12. HCM native Bluetooth subsystem

Matter and MQTT may already be partially or substantially implemented by the
preceding bridge pass. Reuse existing work.

Do NOT duplicate or replace working implementations.

==================================================
3 — FUTURE / RESERVED INTEGRATION
==================================================

Reserve architecture for:

UniFi Protect

but DO NOT implement camera support in this pass.

No current work for:
- camera entities
- streams
- NVR
- RTSP
- ONVIF
- WebRTC
- Scrypted
- UniFi Protect API

The framework must simply remain capable of adding a future UniFi provider
without redesigning HCM core.

==================================================
4 — EXPLICITLY OUT OF SCOPE / RETIRED
==================================================

Do NOT port or implement these Home Assistant integrations:

- AdGuard Home
- Apple TV
- ESPHome
- Fully Kiosk Browser
- GitHub
- HERE Travel Time
- IFTTT
- IPP / printer integration
- Met.no
- OctoPrint
- Radio Browser
- RESTful as a separate HA integration
- Speedtest.net
- Scrypted
- Traeger WiFIRE
- VLC Telnet
- Voice over IP
- WebRTC Camera
- ONVIF
- Network Scanner
- Mail and Packages
- HACS
- Home Assistant Supervisor
- Home Assistant iOS
- Home Assistant Mobile App
- Node-RED Companion
- Watchman
- ZHA
- HA Scheduler integration

Do not spend implementation time reproducing these.

==================================================
5 — NATIVE HCM CAPABILITIES, NOT THIRD-PARTY
==================================================

These capabilities belong to HCM core and must NOT be represented as external
provider integrations:

- Backup
- controlled command execution
- CPU/system metrics
- Grocery Lists / Lists
- Python Scripts
- Bluetooth
- Sun
- Time & Date
- Helpers
- generic host/device health
- automation scheduler
- internal service management

Some may be implemented in separate future passes.

Do not duplicate them as integrations.

==================================================
6 — INTEGRATION REGISTRY
==================================================

Create a central Integration Registry.

Each integration provider must have a stable provider ID.

Suggested examples:

google_calendar
gmail
nws
openweathermap
openai
denon_avr
heos
smartthings
bluetooth
ibeacon
mqtt
matter

Each provider should expose metadata such as:

- provider ID
- display name
- version
- enabled
- configured
- health/status
- last successful communication
- last error
- supported capabilities
- setup/config schema
- credential requirements
- reload support
- disable support
- removal support

==================================================
7 — PROVIDER LIFECYCLE
==================================================

Define a common provider interface.

A provider should be able to implement:

- setup
- start
- stop
- reload
- health check
- discover devices
- refresh state
- subscribe to events
- unregister
- diagnostics

Providers that do not need a capability may leave it unsupported.

Do not require polling if event/subscription APIs exist.

==================================================
8 — DEVICE REGISTRY
==================================================

Create or extend a generic HCM Device Registry.

Third-party devices should have:

- stable internal HCM device ID
- provider ID
- provider-specific external ID
- display name
- manufacturer
- model
- firmware/software version where available
- room assignment where applicable
- online/offline status
- availability source
- integration-specific metadata
- created_at
- updated_at

A provider-specific external ID is NOT the HCM authoritative identity.

Renaming devices must not break automations.

==================================================
9 — ENTITY REGISTRY
==================================================

Create or extend a generic Entity Registry.

Entities may come from:

- native HCM modules/channels
- helpers
- MQTT
- Matter
- SmartThings
- weather
- Bluetooth/iBeacon
- media integrations
- future integrations

Entity records should support:

- stable database ID
- entity_id
- domain
- device_id
- provider ID
- external entity/capability ID
- display name
- room
- enabled
- availability
- state
- attributes
- unit
- device class
- state class where appropriate
- last_updated
- last_changed

Entity IDs are configuration-facing.

Stable database identity remains authoritative.

==================================================
10 — ENTITY DOMAINS
==================================================

Support generic domains needed now and by Automations:

- sensor
- binary_sensor
- switch
- light
- climate
- media_player
- weather
- calendar
- device_tracker
- person
- alarm_control_panel
- button
- number
- select
- text
- event
- update
- automation
- script
- scene
- helper domains already planned

Not every provider needs every domain.

==================================================
11 — STATE MODEL
==================================================

Define a normalized HCM entity-state model.

Each state update should include:

- entity ID / internal entity ID
- state
- typed/native value where appropriate
- attributes
- availability
- timestamp
- source provider
- origin
- correlation ID if available

State transitions should feed the HCM event bus.

Providers should not write directly into automation internals.

==================================================
12 — EVENT REGISTRY / EVENT BUS
==================================================

Create or formalize provider event support.

Examples:

smartthings.device_event
calendar.event_start
calendar.event_end
bluetooth.device_seen
ibeacon.enter
ibeacon.leave
mqtt.message
weather.alert
media.player_changed

Each event should include:

- event type
- provider
- timestamp
- normalized payload
- originating device/entity if applicable
- correlation ID
- raw provider metadata only where useful

Automations should subscribe to normalized events.

==================================================
13 — SERVICE / ACTION REGISTRY
==================================================

Create a central service/action registry.

Providers register callable actions using domain/service semantics.

Examples:

media_player.volume_set
media_player.select_source
calendar.create_event
notify.send
smartthings.refresh_device

Each registered service should declare:

- domain
- service name
- display name
- description
- target requirements
- argument schema
- return/response schema
- permissions
- timeout behavior
- whether it mutates physical state
- provider

This registry must be discoverable by the future Automation visual editor.

==================================================
14 — DYNAMIC UI SCHEMA
==================================================

Provider configuration and actions should use machine-readable schemas so the
frontend can generate forms dynamically.

Example service definition:

media_player.volume_set

fields:
- volume_level:
    type: number
    min: 0.0
    max: 1.0
    required: true

This prevents every new integration from requiring custom automation editor
code.

Custom provider UI may still be allowed when genuinely necessary.

==================================================
15 — CREDENTIAL / SECRET STORAGE
==================================================

Do not store provider secrets directly in normal configuration JSON/YAML.

Use the existing HCM secret/credential model if one exists.

Otherwise add a secure credential-reference layer.

Secrets include:

- API keys
- OAuth refresh tokens
- client secrets
- access tokens
- provider passwords

Requirements:

- encryption at rest if existing architecture supports it
- never returned through normal API
- never logged
- never exposed in diagnostics
- referenced by stable credential ID
- ADMIN only for creation/update

==================================================
16 — OAUTH SUPPORT
==================================================

Build reusable OAuth support for integrations such as:

- Google Calendar
- Gmail
- SmartThings

Support:

- authorization URL
- callback
- authorization code exchange
- refresh tokens
- access-token refresh
- token expiration
- reconnect flow
- revoked credentials
- health status

Provider-specific OAuth logic should plug into common framework code.

Do not duplicate a complete OAuth implementation for each provider.

==================================================
17 — WEBHOOK SUPPORT
==================================================

Some providers, especially SmartThings, may need inbound webhooks.

Build reusable provider-webhook support:

- unique provider callback IDs
- authentication/signature verification
- body size limits
- rate limiting
- provider ownership
- event normalization
- replay protection where applicable

Provider webhooks must not directly command HCM outputs.

They produce state/events which HCM processes normally.

==================================================
18 — POLLING / SUBSCRIPTION MODEL
==================================================

Support both:

- provider push/subscription
- provider polling

Polling providers need:

- configurable interval with sane provider-specific minimums
- backoff
- jitter if appropriate
- failure handling
- last success
- stale state handling

Do not hammer cloud APIs.

Event/subscription providers should prefer push updates.

==================================================
19 — HEALTH / STATUS
==================================================

Every integration should expose:

- Connected
- Degraded
- Disconnected
- Authentication Required
- Disabled
- Configuration Required
- Error

Also expose:

- last successful update
- last error
- retry state
- device count
- entity count

This should be visible in Settings -> Devices & Services.

==================================================
20 — FRONTEND: DEVICES & SERVICES
==================================================

Add or prepare:

Settings
  -> Devices & Services

Tabs:

- Integrations
- Devices
- Entities
- Helpers

If Helpers are implemented by the Automation pass, integrate with that page
rather than duplicating them.

==================================================
21 — INTEGRATIONS PAGE
==================================================

Cards should look conceptually similar to:

SmartThings
Connected
4 devices
19 entities

Google Calendar
Connected
2 calendars
Healthy

OpenWeatherMap
Connected
12 entities

Controls:

- Configure
- Devices
- Entities
- Diagnostics
- Reload
- Disable
- Remove

Add:

+ Add Integration

==================================================
22 — ADD INTEGRATION FLOW
==================================================

User selects a provider.

The provider supplies its setup schema.

Possible setup methods:

- OAuth
- API key
- LAN discovery
- host/IP
- native hardware
- existing broker/service

Never require provider-specific setup code in core UI when schema-driven setup
is sufficient.

==================================================
23 — DEVICE PAGE
==================================================

Each device page should show:

- name
- integration/provider
- manufacturer/model
- room
- availability
- entities
- useful diagnostics
- provider metadata
- disable/remove where supported

Entity state should update live if existing frontend event infrastructure allows.

==================================================
24 — ENTITY PAGE
==================================================

Entity page should show:

- entity ID
- internal stable ID
- domain
- provider
- device
- room
- state
- attributes
- availability
- enabled
- last changed
- last updated

Allow entity rename/entity-ID change only under existing HCM naming policy.

==================================================
25 — GOOGLE CALENDAR
==================================================

Implement or scaffold clean Google Calendar provider support.

Use Google Calendar API.

Needs:

- OAuth
- calendar discovery
- per-calendar entity
- next event
- start/end
- summary/title
- description
- location
- all-day status
- event UID
- timezone-aware timestamps

Calendar events should feed HCM normalized calendar events suitable for
Automation triggers.

Future UI may embed or present calendar data.

Do not require Home Assistant.

==================================================
26 — GMAIL
==================================================

Implement or scaffold Gmail provider support using Gmail API.

Use common Google OAuth framework.

Initial capabilities should focus on:

- account connection/health
- unread count or useful mailbox sensors
- message/thread discovery only where intentionally configured
- future automation-trigger support through normalized events

Do not recreate a full email client unless required.

Do not expose message bodies or private mail content broadly through generic
diagnostics.

==================================================
27 — NATIONAL WEATHER SERVICE
==================================================

Implement direct NWS integration.

Normalize useful data into HCM weather/sensor entities.

At minimum consider:

- current conditions where available
- forecast
- temperature
- precipitation probability
- wind
- alerts
- alert severity
- alert event
- forecast periods

Use proper API identification/User-Agent requirements.

Respect provider limits.

NWS alert updates should be normalized events suitable for Automations.

==================================================
28 — OPENWEATHERMAP
==================================================

Implement OpenWeatherMap provider.

Use API key credential storage.

Normalize:

- current conditions
- forecast
- temperature
- feels-like
- humidity
- pressure
- wind
- precipitation
- cloud coverage
- weather condition

Keep weather-provider specifics out of the Automation Engine.

==================================================
29 — WEATHER ABSTRACTION
==================================================

NWS and OpenWeatherMap should feed a common HCM weather model.

Example:

weather.home

Attributes may include:

- condition
- temperature
- apparent_temperature
- humidity
- wind_speed
- wind_direction
- precipitation_probability
- forecast
- provider

Provider-specific raw fields may remain in diagnostics.

Do NOT make Sun calculations dependent on cloud weather providers.

==================================================
30 — OPENAI
==================================================

Implement OpenAI as an integration provider rather than hardcoding requests
throughout HCM.

Credential:
- API key

Provider should expose controlled services such as:

openai.generate_text

and potentially future:
- summarize
- classify
- structured response

Do not permit arbitrary secret access in prompts.

Do not make life-safety decisions depend on OpenAI.

Automation use must have explicit timeout/error handling.

==================================================
31 — DENON AVR
==================================================

Implement Denon AVR support using an established maintained library/protocol
where practical.

Do NOT reimplement the entire Denon network protocol from scratch unless
necessary.

Preferred architecture:

Denon adapter
   ->
HCM media_player entities

Support useful receiver capabilities such as:

- power
- volume
- mute
- source/input
- sound mode if exposed
- main zone
- additional zones where available
- availability
- device info

Register normalized services:

media_player.turn_on
media_player.turn_off
media_player.volume_set
media_player.volume_up
media_player.volume_down
media_player.volume_mute
media_player.select_source

Use asynchronous/event-based updates if supported.

==================================================
32 — HEOS
==================================================

Implement HEOS separately from AVR control but through the same normalized
media layer.

Use established HEOS protocol/library where practical.

Support:

- player discovery
- player state
- play/pause/stop
- volume
- mute
- source/media information
- groups where supported
- favorites where useful
- availability

Expose devices as HCM media_player entities.

Do not merge HEOS provider internals with Denon AVR provider internals.

They may share the common HCM media abstraction.

==================================================
33 — MEDIA ABSTRACTION
==================================================

Create a provider-independent media model sufficient for Denon and HEOS.

Potential common state:

- state
- volume_level
- muted
- source
- source_list
- media_title
- media_artist
- media_album
- sound_mode
- group membership
- availability

Do not overbuild a universal media platform beyond current needs.

==================================================
34 — SMARTTHINGS
==================================================

SmartThings is a required provider.

Use official SmartThings cloud APIs.

Production design should use OAuth rather than depending permanently on manual
personal access tokens.

Support:

- OAuth
- device discovery
- device capability discovery
- device state
- commands
- event subscriptions/webhooks
- reconnect/re-authentication
- provider health

Translate SmartThings capabilities into normalized HCM entities.

Do not expose raw SmartThings JSON as the normal automation interface.

==================================================
35 — SMARTTHINGS DEVICE MAPPING
==================================================

Initially prioritize devices the user already depends on, especially
washer/dryer state.

Examples may normalize to:

sensor.washer_job_state
sensor.washer_machine_state
sensor.dryer_job_state
sensor.dryer_machine_state

Support capability-driven mapping rather than appliance-name special cases
where possible.

If an unknown capability cannot be normalized:

- preserve it as provider diagnostic/raw capability data
- do not silently discard it
- optionally expose a generic sensor/event only when safe and meaningful

==================================================
36 — SMARTTHINGS COMMAND PATH
==================================================

Commands:

Automation
   ->
HCM service registry
   ->
SmartThings provider
   ->
SmartThings API

Do not let imported HA SmartThings services bypass normal service authorization.

Trace:

- requested command
- target device
- provider acceptance
- response/failure

==================================================
37 — BLUETOOTH
==================================================

Bluetooth is a native HCM subsystem, not a cloud integration.

Use HCM host Bluetooth hardware.

Create:

- adapter status
- discovery
- known-device registry
- BLE advertisement processing
- signal/RSSI
- presence/last seen
- manufacturer/service data where useful
- provider health

Do not require Home Assistant.

==================================================
38 — IBEACON
==================================================

iBeacon support should build on the HCM Bluetooth subsystem.

Do NOT create a completely separate Bluetooth stack.

Parse appropriate BLE iBeacon advertisements.

Support registered beacon identity using:

- UUID
- major
- minor

Expose entities/events such as:

device_tracker.<beacon>
binary_sensor.<beacon>_present
sensor.<beacon>_rssi

Possible normalized events:

ibeacon.seen
ibeacon.enter
ibeacon.leave

Presence thresholds/timeouts should be configurable.

Do not claim precise indoor positioning from RSSI.

==================================================
39 — MQTT
==================================================

Reuse existing HCM MQTT bridge/provider work.

Do not duplicate it.

Ensure MQTT fits the generic Integration / Device / Entity / Service / Event
registries.

MQTT should be able to register external devices/entities separately from HCM's
outbound bridge entities.

==================================================
40 — MATTER
==================================================

Reuse existing Matter bridge work.

Do not rewrite it.

Ensure Matter export/provider status appears in the Integration framework.

If Matter controller/import support exists by this starting SHA, register
imported devices/entities through the same generic registries.

If not implemented yet, expose truthful capability/status only.

==================================================
41 — CAMERA FUTURE RESERVATION
==================================================

No camera implementation now.

However the Integration SDK must permit a future:

unifi_protect

provider to register:

- devices
- camera entities
- motion events
- doorbell events
- online/offline state
- future snapshots/stream capabilities

Do not add camera-specific core dependencies in this pass.

A future UniFi integration must be implementable as a provider plugin rather
than a core rewrite.

==================================================
42 — HOMEKIT
==================================================

Do not implement HomeKit Bridge.

Matter is the preferred Apple Home export path.

Only revisit native HomeKit later if a concrete device/capability gap cannot be
covered through Matter.

==================================================
43 — ZIGBEE
==================================================

Do not implement ZHA.

Current likely future paths:

A:
Zigbee coordinator
 -> Zigbee2MQTT
 -> HCM MQTT

or

B:
future SIM-native Zigbee interface

Do not make current Integration Framework depend on either choice.

Both must ultimately be capable of registering normalized HCM entities.

==================================================
44 — SERVICE AVAILABILITY FOR AUTOMATIONS
==================================================

The Automation Engine must be able to ask:

- does service exist?
- is provider enabled?
- is provider healthy?
- does target exist?
- what schema does service require?

This allows imported automations to distinguish:

SUPPORTED
UNAVAILABLE_PROVIDER
NEEDS_MAPPING
UNSUPPORTED

Do not mark valid automation syntax invalid just because a provider is absent.

==================================================
45 — PROVIDER RELOAD / FAILURE ISOLATION
==================================================

A broken third-party provider must not crash HCM.

Provider failure must be isolated.

If a provider fails:

- mark provider degraded/error
- mark affected entities unavailable as appropriate
- preserve HCM operation
- preserve automation engine operation
- preserve Heartbeat
- preserve life safety
- retry with bounded backoff where appropriate

==================================================
46 — LIFE SAFETY BOUNDARY
==================================================

Third-party integrations must NEVER become authoritative for HCM fire/life
safety.

Do not route fire authority through:

- SmartThings
- weather
- Google
- OpenAI
- Bluetooth
- MQTT third-party devices
- future cameras

Existing life-safety architecture remains independent.

==================================================
47 — DATABASE MODEL
==================================================

Audit existing schema before adding tables.

Likely concepts needed:

integration_providers
integration_instances
integration_credentials references
devices
entities
entity_states/current state
service_definitions
provider_webhooks
provider_diagnostics or status

Reuse existing relevant tables where safe.

Do not duplicate channel_metadata or module tables unnecessarily.

Native module/channel identity must remain intact.

==================================================
48 — MIGRATION SAFETY
==================================================

Forward migrations only.

Before any live deployment:

- backup production DB
- clone/restore DB
- apply migrations to clone
- verify:
  - users/auth
  - rooms
  - channel metadata
  - bindings
  - module commissioning
  - bridge settings
  - Matter endpoints
  - existing config

Do not alter physical output configuration.

==================================================
49 — AUTHORIZATION
==================================================

ADMIN:
- add integration
- configure
- reconnect OAuth
- disable
- reload
- remove
- edit credentials
- map devices/entities

READONLY:
- inspect integrations
- inspect devices/entities
- inspect status/diagnostics
- cannot configure/reconnect/remove

Automation execution permissions continue to use existing HCM command model.

==================================================
50 — AUDIT
==================================================

Audit administrative changes:

- integration added
- integration removed
- integration disabled/enabled
- configuration changed
- credential replaced
- OAuth reconnected
- entity mapping changed
- provider manually reloaded

Do not fill administrative audit logs with every state update.

==================================================
51 — DIAGNOSTICS
==================================================

Provide provider diagnostics that are safe to export.

Include:

- provider name/version
- status
- device/entity counts
- last success
- sanitized last error
- subscription/polling status
- provider capability flags

Redact:

- API keys
- OAuth tokens
- passwords
- auth headers
- personal message content
- private email bodies

==================================================
52 — RATE LIMIT / BACKOFF
==================================================

Cloud providers must have:

- request timeouts
- retry/backoff
- rate-limit handling
- stale-state handling
- connection health

One misbehaving automation must not cause API request storms.

Service registry/providers should be able to enforce provider-specific command
throttling.

==================================================
53 — TESTING
==================================================

Use provider mocks/fixtures.

Do not require live third-party credentials in normal CI.

Required focused test coverage:

Framework:
- provider registration
- provider lifecycle
- device registration
- entity registration
- state updates
- events
- services
- failure isolation
- disabled provider behavior
- credential redaction

OAuth:
- auth flow state validation
- token refresh
- revoked token behavior

Weather:
- NWS normalization
- alerts
- OWM normalization

Media:
- Denon entity/service normalization
- HEOS entity/service normalization

SmartThings:
- device discovery mock
- capability mapping
- state event/webhook
- command request
- auth expiration

Bluetooth:
- advertisement parsing
- iBeacon parsing
- presence timeout
- duplicate advertisement handling

Frontend:
- Integration cards
- Devices tab
- Entities tab
- add/configure flow
- READONLY protection
- provider status

==================================================
54 — NO LIVE THIRD-PARTY AUTH DURING CI
==================================================

CI must not require:

- Google account
- Gmail account
- SmartThings account
- OpenWeatherMap API key
- OpenAI key
- actual Denon receiver
- actual HEOS player
- Bluetooth beacon
- live NWS success

Use mocks.

Manual integration testing can occur later with explicit user authorization and
credentials configured through HCM.

==================================================
55 — DOCUMENTATION
==================================================

Add authoritative documentation:

INTEGRATIONS_AND_PROVIDERS.md

Document:

- provider architecture
- lifecycle
- device registry
- entity registry
- state model
- event model
- service registry
- credential handling
- OAuth
- webhooks
- UI
- failure isolation
- current integrations
- retired HA integrations
- future UniFi reservation
- Zigbee future options
- safety boundary

Update IMPLEMENTATION_STATUS.md truthfully.

==================================================
56 — IMPLEMENTATION ORDER
==================================================

PASS A
Framework:
- provider registry
- device registry
- entity registry
- service registry
- events
- credentials
- provider status

PASS B
Frontend:
- Devices & Services
- Integrations
- Devices
- Entities
- setup/config UI
- status/diagnostics

PASS C
Shared provider foundations:
- OAuth
- webhook framework
- polling/subscription lifecycle
- weather abstraction
- media abstraction
- Bluetooth subsystem

PASS D
Providers:
- NWS
- OpenWeatherMap
- OpenAI
- Google Calendar
- Gmail

PASS E
Providers:
- SmartThings
- Denon AVR
- HEOS
- iBeacon

PASS F
Registry integration:
- existing MQTT
- existing Matter

PASS G
- docs
- regression tests
- full validation

Do not implement UniFi/cameras in this pass.

==================================================
57 — DEPLOYMENT SCOPE
==================================================

This pass may be deployed to HCM only after validation and with normal
deployment safeguards.

Deployment must NOT:

- actuate physical outputs
- modify fire inputs
- modify life-safety configuration
- alter commissioning
- change module I/O
- run HIL
- send device commands to SmartThings/Denon/etc. without explicit manual test
  authorization

Safe live verification includes:

- integration page loads
- provider records
- disabled/config-required provider status
- entity/device registry
- OAuth callback route existence
- mocked/local test provider if included
- existing MQTT/Matter state still healthy

==================================================
58 — ACCEPTANCE CRITERIA
==================================================

Framework is ready when:

1. a provider can register itself
2. provider can register devices
3. devices can register entities
4. entity state changes flow through HCM
5. provider can register services/actions
6. provider can emit events
7. services are discoverable by Automation layer
8. provider failures are isolated
9. credentials are not exposed
10. frontend lists integrations
11. frontend lists devices
12. frontend lists entities
13. ADMIN can configure providers
14. READONLY cannot mutate
15. OAuth-capable provider framework exists
16. webhook-capable provider framework exists
17. Bluetooth/iBeacon can fit the same entity/event model
18. existing MQTT/Matter fit the same model
19. future UniFi provider would not require core redesign

==================================================
59 — FINAL VALIDATION
==================================================

At end:

Run focused tests during development.

Then once:

python -m pytest

Then:

python -m compileall -q \
  00_Heartbeat \
  01_HCM \
  02_SIM \
  03_LCM \
  04_RCM \
  05_PNL \
  06_config \
  07_servises \
  10_scripts \
  11_tests \
  12_hardware_tests

Run JavaScript syntax validation once.

Run:

git diff --check

Run migration/config validation once.

Build deployment image if relevant.

Verify hosted CI on exact ending SHA.

==================================================
60 — FINAL REPORT
==================================================

Return:

1. starting SHA
2. ending SHA
3. migrations added
4. provider framework architecture
5. device registry design
6. entity registry design
7. state model
8. event model
9. service/action registry
10. credential storage
11. OAuth framework
12. webhook framework
13. polling/subscription framework
14. frontend integration page
15. device page
16. entity page
17. NWS status
18. OpenWeatherMap status
19. OpenAI status
20. Google Calendar status
21. Gmail status
22. SmartThings status
23. Denon AVR status
24. HEOS status
25. Bluetooth status
26. iBeacon status
27. MQTT registry integration status
28. Matter registry integration status
29. future UniFi readiness
30. retired integrations confirmed not implemented
31. focused tests
32. full pytest
33. compileall
34. JS validation
35. diff check
36. migration validation
37. hosted CI exact SHA/result
38. live deployment result if performed
39. /health
40. /api/v1/version
41. auth/login verification
42. PostgreSQL status
43. Heartbeat status
44. git status
45. remaining limitations

Final classification:

HCM_INTEGRATION_FRAMEWORK_READY

or

HCM_INTEGRATION_FRAMEWORK_PARTIAL