
Repository:
pengels22/HomeControl

Branch:
main

Starting SHA:
98a939d0d59046d0bf09cd215c9313d5e218a40e

IMPORTANT

Read and follow AGENTS.md before changing anything.

In particular:
- use focused tests while developing
- do not repeatedly run the full suite
- run the full pytest suite once at the end
- rerun the full suite only once more if fixes are required
- avoid unnecessary full-repo rescans

GOAL

Finish the work left incomplete by the previous metadata/rooms/HVAC/PNL/bridge
implementation.

Do NOT start the Automations page yet.

This task is ONLY for:

1. HCM-local MQTT broker deployment
2. secure MQTT broker configuration/persistence
3. generic inbound MQTT device registration into HCM
4. completing MQTT bridge operational integration
5. completing Matter bridge deployment/runtime integration
6. preparing Matter controller/import architecture only if practical
7. live HCM deployment of the completed bridge work
8. verification/documentation

==================================================
1 — CURRENT STATE TO PRESERVE
==================================================

The following already exists and must not be regressed:

- channel_metadata DB model
- stable room IDs
- RCM/LCM common channel metadata
- LCM dimmer LIGHTING lock
- purpose enum:
  LIGHTING / HVAC / LANDSCAPE / GENERAL / SECURITY / OTHER
- MQTT/Matter exposure flags
- emergency LIGHTING flag
- HVAC semantic roles
- RCM local heat/cool interlock
- HCM thermostat semantic mapping and transition fix
- PNL room associations and room-based lighting projection
- persistent Matter endpoint allocation
- MQTT export bridge
- Matter export bridge
- hosted CI green on 98a939d

Do not redesign or duplicate these systems.

==================================================
2 — HCM-LOCAL MQTT BROKER
==================================================

HCM must not depend on the Home Assistant Mosquitto broker.

Add an HCM-local Mosquitto deployment as part of the HCM stack.

Expected architecture:

HCM host
├── HCM application
├── PostgreSQL
├── Unified Heartbeat
├── Mosquitto broker
└── Matter bridge runtime

Internal HCM broker connection:
    localhost:1883
or the correct Docker service hostname if broker isolation requires that.

External local/control-network endpoint:
    192.168.20.27:1883

Do NOT expose MQTT to WAN.

==================================================
3 — MQTT SECURITY
==================================================

Broker requirements:

- anonymous access disabled
- no passwords/secrets committed to Git
- use existing HCM protected secret/environment conventions
- create/use an HCM MQTT service credential
- broker persistence survives HCM app container replacement
- broker config survives reboot
- support local LAN/control-network clients
- architecture should allow TLS on 8883 later
- do not require TLS for this initial local deployment unless already practical

Do not hardcode credentials.

==================================================
4 — MQTT DEPLOYMENT INTEGRATION
==================================================

Add broker deployment/configuration to the supported HCM deployment path.

Do not create an unrelated manual-only install path.

Preserve:
- PostgreSQL container/data
- Heartbeat host service
- watchdog behavior
- existing rollback process
- HCM application container isolation

If Mosquitto runs as:
- separate container, document/persist it properly
or
- host service, integrate with systemd/runbooks

Choose the least disruptive supported architecture.

==================================================
5 — UPDATE HCM MQTT DEFAULTS
==================================================

Current bridge defaults assume an external broker / 8883 / TLS.

Change defaults to match HCM-local deployment:

host:
    localhost or deployment service hostname

port:
    1883

tls:
    false

Credentials still come from protected environment/secrets.

Keep DB settings override support.

Do not break future TLS support.

==================================================
6 — OUTBOUND MQTT BRIDGE
==================================================

Preserve existing behavior:

Only channels with:
    mqtt_enabled == true

are exported.

Preserve:

- stable IDs
- Home Assistant MQTT Discovery
- retained discovery
- state publication
- availability
- rename updates
- room metadata
- topic cleanup/journaling
- command reauthorization through HCM
- retained command rejection
- no direct bypass to modules

Verify this against the new local broker.

==================================================
7 — GENERIC INBOUND MQTT DEVICES
==================================================

Add HCM support for external MQTT devices that publish into the HCM-local broker.

Do NOT treat every arbitrary topic as an HCM device.

Add a managed registration/configuration model.

Each inbound MQTT device/input should support at least:

- stable HCM ID
- display name
- room_id
- enabled
- device/input type
- state_topic
- optional command_topic
- optional availability_topic
- online/offline payloads if applicable
- payload mapping
- optional unit
- optional device_class / semantic type
- timestamps / last state
- last seen if useful

Examples:

Garage Door Sensor
- type: CONTACT
- state_topic: garage/door/state
- open -> OPEN
- closed -> CLOSED

ESP32 Temperature
- type: TEMPERATURE
- state_topic: shop/temp
- numeric payload
- unit: F

Presence Sensor
- type: OCCUPANCY
- state_topic: livingroom/presence

Normalize inbound state into HCM-native state/events.

Do not make automations depend on raw MQTT topic strings if a registered device
exists.

==================================================
8 — INBOUND MQTT SECURITY / VALIDATION
==================================================

Inbound messages must:

- only affect registered/enabled MQTT devices
- validate payload mappings/types
- reject malformed values
- never gain direct module-control authority merely by publishing a topic
- use HCM command/arbitration path for commandable entities
- honor maintenance/safety/commissioning controls

Arbitrary publish != trusted HCM control.

==================================================
9 — MQTT API/UI
==================================================

Extend authenticated API/UI for inbound MQTT devices.

Settings > MQTT should support:

- broker status
- connection state
- configured host/port/TLS
- registered inbound MQTT devices
- add/edit/disable MQTT device
- state topic
- optional command topic
- availability topic
- room
- semantic type
- payload mapping

ADMIN:
    may configure

READONLY:
    may inspect

Do not expose passwords in UI or API responses.

==================================================
10 — MATTER EXPORT BRIDGE
==================================================

Preserve current implemented export behavior:

LIGHTING relay:
    Matter On/Off Light

LIGHTING dimmer:
    Matter Dimmable Light

Preserve:
- persistent endpoint IDs
- PostgreSQL allocation
- stable IDs through rename/restart
- HCM authorization of external commands
- persistent Matter SDK storage
- no direct module bypass

==================================================
11 — MATTER LIVE DEPLOYMENT SUPPORT
==================================================

Finish runtime deployment integration so the Matter process can actually run
persistently with HCM.

Provision/document:

- HCM_MATTER_STORAGE persistent directory
- HCM_MATTER_PASSCODE protected secret
- optional port/discriminator
- correct container filesystem mount
- IPv6/mDNS requirements
- restart behavior
- status reporting

Do not claim commissioning success until actually paired to a Matter fabric.

==================================================
12 — MATTER CONTROLLER / IMPORT
==================================================

HCM eventually needs to consume third-party Matter devices too.

For this task:

Audit whether current matter.js version can support controller/commissioner mode
cleanly in the existing runtime.

If practical without a major rewrite:
- add minimal controller/import scaffolding
- persist imported Matter node identity
- normalize imported device state into HCM registry
- do NOT complete or claim live commissioning unless tested

If this would materially expand the task:
- do NOT implement a half-baked controller
- document the exact required next step
- leave export bridge clean and complete

Do not compromise the export bridge to force controller support into this pass.

==================================================
13 — DO NOT START AUTOMATIONS
==================================================

Do not implement:

- automation engine
- automation UI
- calendar triggers
- sunrise/sunset
- MQTT automation triggers
- Matter automation triggers
- scenes

Those are the next design/implementation phase.

This task only finishes bridge infrastructure.

==================================================
14 — DATABASE / MIGRATIONS
==================================================

If inbound MQTT devices require schema changes:

- add a new forward migration
- preserve migration 008
- do not rewrite applied migrations
- preserve users/auth/rooms/bindings/channel metadata
- test migration on a restored clone before live deployment

Use stable IDs and foreign keys to existing rooms where appropriate.

==================================================
15 — LIVE DEPLOYMENT
==================================================

After code/tests are green:

Live HCM deployment is authorized.

Requirements:

- back up live DB
- restore/test migration clone if migration added
- preserve rollback HCM image/container
- deploy exact tested SHA
- install/start Mosquitto without restarting unrelated services
- preserve PostgreSQL
- preserve Unified Heartbeat
- preserve watchdog
- do not actuate outputs
- do not run HIL tests
- do not change RCM/LCM commissioning state

Only restart what is required for HCM/MQTT/Matter deployment.

==================================================
16 — LIVE VERIFICATION
==================================================

Verify:

HCM:
- /health healthy
- /api/v1/version exact SHA
- login works
- existing safety API still works
- metadata APIs still work

MQTT broker:
- active
- anonymous login rejected
- authenticated HCM connection succeeds
- persistence path valid
- broker survives HCM app restart
- local publish/subscribe test succeeds

MQTT outbound:
- enabled HCM channel publishes discovery/state
- disabled channel is not exported
- commands still route through HCM

MQTT inbound:
- registered test device publishes state
- HCM receives/normalizes it
- malformed/unregistered topic does not create/control devices

Matter:
- bridge process starts
- persistent storage used
- endpoint registry loads
- light/dimmer endpoint construction succeeds
- status truthfully says fabric pairing unverified if not commissioned

Do not actuate real outputs for these checks.

==================================================
17 — TEST POLICY
==================================================

Follow AGENTS.md.

During development:
- focused tests only
- targeted DB tests if schema changes
- targeted MQTT tests
- targeted Matter tests

At the end:

Run full pytest ONCE.

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

Run:
git diff --check

Run JS syntax checks once.

Run Matter adapter validation once.

Run MQTT broker/config validation once.

If full pytest fails:
- fix using only focused failing tests
- rerun full pytest one final time only

==================================================
18 — DOCUMENTATION
==================================================

Update authoritative docs with:

- HCM-local MQTT broker architecture
- broker auth/persistence
- external endpoint 192.168.20.27:1883
- future 8883/TLS path
- outbound MQTT bridge
- inbound MQTT device registration
- Matter runtime deployment
- Matter export status
- Matter controller/import status
- remaining commissioning limitations

Do not claim Home Assistant dependency.

Home Assistant Discovery is compatibility only.

==================================================
FINAL REPORT
==================================================

Return:

1. starting SHA
2. ending SHA
3. files/migrations added
4. Mosquitto deployment model
5. broker persistence location
6. anonymous-access result
7. HCM MQTT service credential mechanism
8. broker host/port used internally
9. external broker endpoint
10. outbound MQTT bridge status
11. inbound MQTT device model
12. inbound MQTT API/UI
13. Matter export bridge status
14. Matter persistent storage path
15. Matter fabric commissioning status
16. Matter controller/import status
17. focused test results
18. full pytest result
19. compile result
20. JS syntax result
21. Matter validation result
22. MQTT validation result
23. migration clone-test result if applicable
24. live deployment result
25. live /health
26. live /api/v1/version
27. live login check
28. PostgreSQL state
29. Heartbeat state
30. Mosquitto state
31. Matter process state
32. hosted CI exact SHA/result
33. git status
34. remaining blockers

Final classification:

BRIDGES_INFRASTRUCTURE_READY

or

BRIDGES_INFRASTRUCTURE_PARTIAL