# Channel metadata, rooms, HVAC semantics and bridges

HCM and PostgreSQL remain the configuration and control authority. Migration 008
adds a shared channel registry; it does not replace logical devices, bindings,
authentication, room_hvac, commissioning, or the installed VLAN 20 topology.

## Durable identities and migration

`channel_metadata.id` is a stable numeric key. `(module_id, channel_id)` is unique
and immutable, as is `channel_kind`. Names are presentation data. Foreign keys
reuse `modules` and `rooms`. Records include display_name, room_id, enabled,
purpose, mqtt_enabled, matter_enabled, emergency, hvac_control,
hvac_description, security_endpoint_label, other_function, and timestamps.

RCM relays default to GENERAL. LCM relays default to LIGHTING. LCM LV and HV
dimmers are locked to LIGHTING in shared validation and SQL constraints. The
identity trigger prevents changing a dimmer into a relay to bypass the lock.
The existing profile has A1–A8, 10-1–10-10, and HV-1–HV-4; this change does not
alter pinouts or delete the two additional LV identities in the audited source.
Role changes retain old channel records, disable incompatible channels, and
seed the new profile. They do not commission or actuate outputs.

Migration 008 seeds existing and newly registered RCM/LCM channels, preserves
bound names/rooms and explicit emergency designations, and imports existing HCM
channel configuration files within the deliberate migration transaction.
Malformed legacy files or conflicting safety semantics abort the migration.
The numbered runner records successful application; startup never migrates.

## Purpose semantics

Purposes are LIGHTING, HVAC, LANDSCAPE, GENERAL, SECURITY and OTHER.
Emergency is a LIGHTING-only flag, not a separate purpose. HVAC requires one
of G, Y1, Y2, W1, W2, O/B, AUX, E or OTHER_HVAC. R/common is not a channel role.
OTHER_HVAC allows a short description. SECURITY allows an endpoint label; OTHER
allows a free-form function. Purpose changes must explicitly clear incompatible
fields. Both API and database reject stale incompatible fields.

MQTT and Matter flags default false. They authorize export only and have no
bearing on HCM operation or PNL visibility. Channel enable is separate from
module commissioning. There is no channel commissioning concept.

## Rooms and PNL

Existing `rooms.id` remains the durable identity. Renaming does not change
channel, HVAC or panel associations. DELETE in the API disables the room instead
of destroying associations/history. Disabled rooms remain inspectable.
`pnl_rooms` is a many-to-many relationship with at most one primary room per
panel. The initial UI edits a Primary Room.

The native PNL projection selects enabled LIGHTING channels in enabled rooms
assigned to the panel. No MQTT/Matter predicate is used. Changes are recomputed
from the registry and delivered on the authenticated module session. Unbound
channels can be listed but cannot bypass logical-binding control authorization.
Panel controls use HCM's existing authenticated command path.

## HVAC and safety

The thermostat resolves G (fan), W1 (single-stage heat), and Y1 (single-stage
cool) through metadata and logical bindings. It switches the opposing family
OFF before any ON call and keeps non-primary stages off. Existing logical
names remain a compatibility fallback when no semantic HVAC rows exist.
This single-stage controller does not invent staging, heat-pump reversing-valve
polarity, AUX policy, or OTHER_HVAC behavior. O/B and OTHER_HVAC are OFF-only
in the thermostat's all-off path.

HEAT/COOL transitions first drop the previous family, record its off timestamp,
and preserve fan post-run. Destination restart lockouts, same-mode minimum runs,
damper lead, fan lead and failed-sensor damper behavior remain in place.
A controller mutex and a serialized HCM semantic dispatch interlock reject
opposing active or unknown calls, including calls on different modules.
Semantic HVAC energization requires the current metadata snapshot to have been
acknowledged by the module. Old agents cannot falsely acknowledge this contract.

RCM persists the authoritative metadata snapshot without actuating outputs.
Its local interlock allows G alone or with multiple stages of one family, and
rejects HEATING (W1/W2/AUX/E) plus COOLING (Y1/Y2). O/B is a separate reversing
role. A rejection leaves the conflicting requested output unenergized; RCM is
not a thermostat. Cached metadata survives reconnect/restart.

Fire shutdown adds a non-energizing metadata_hvac_off operation, covering even
unbound classified relays. It independently attempts every known target and
reports driver failures. Legacy hvac_shutdown_channels and binding shutdown
flags remain as a conservative compatibility union; remove them only after
reviewed metadata delivery and module validation. Initialized drivers can
perform safety OFF without normal energization permission. Normal energization
still requires every existing module commissioning and output gate.

Emergency selection uses enabled LIGHTING + emergency metadata, falling back
to legacy logical metadata only where no channel registry record exists.
Maintenance lockout remains above FIRE_FORCE_ON. Sensor inputs keep reporting.
Dedicated HCM safety relays remain separate. No physical fire, HVAC, relay,
lighting, CAN, or notification validation is implied by software tests.

## Registry synchronization and MQTT

Transactional PostgreSQL NOTIFY events cover channels, rooms, modules, bindings,
panel assignments, and bridge settings. A centralized HCM task recomputes the
projections, with periodic reconciliation for reconnects and interrupted
delivery. Separate bridge stores do not own device configuration.

The MQTT adapter uses aiomqtt 2.x and Home Assistant retained discovery. Its
stable unique ID prefers logical-device ID, falling back to channel registry
ID. Renames and room changes update presentation, not identity. A purpose/type
change removes obsolete discovery topics. A database publication journal makes
retained-topic removal recoverable across process restart. Commands are never
retained; received retained commands are rejected. Commands are revalidated
against current exposure flags and pass through HCM logical arbitration.
State is module-reported command state, not proof of physical load feedback.
Availability requires an online control session and an enabled unlocked binding.

Settings exposes broker hostname, port, TLS and enable. Broker credentials stay
in HCM_MQTT_USERNAME/HCM_MQTT_PASSWORD in the host's protected environment.
TLS uses system CA verification. HCM_MQTT_HOST/PORT/TLS provide initial defaults.
Without a configured broker the adapter reports disabled; installing code does
not establish broker connectivity or Home Assistant acceptance.

## Matter

The optional supervised Node process uses pinned `@matter/main` 0.17.9.
LIGHTING relays map to On/Off Light; dimmers map to Dimmable Light. Other
purposes report unsupported and are omitted; a generic relay is not mislabeled
as a socket. Names use configured HCM display names. Absolute brightness is
supported; continuous move/step requests are rejected rather than simulated.

`matter_endpoints` allocates endpoint numbers from a PostgreSQL identity
sequence starting at 2 (root 0, aggregator 1). Records survive disable/rename;
module deletion leaves tombstones. Numbers are never compacted or reused.
The adapter uses these explicit numbers and stable channel IDs, while fabric
credentials and protocol state use persistent Matter SDK storage. External
commands await HCM acceptance and cannot directly control a module.

Provision HCM_MATTER_STORAGE to a persistent HCM data subdirectory and
HCM_MATTER_PASSCODE in a protected host environment before enabling Matter in
Settings. Optional HCM_MATTER_PORT and HCM_MATTER_DISCRIMINATOR select protocol
parameters. Container/network reachability for IPv6/mDNS and fabric pairing
requires deployment-specific validation. The development bridge uses SDK test
vendor/product credentials; no certification or commissioned fabric is claimed.

Reference interfaces: [aiomqtt](https://aiomqtt.bo3hm.com/subscribing-to-a-topic)
and the [Matter.js bridge example](https://github.com/matter-js/matter.js/blob/main/examples/device-bridge-onoff/src/BridgedDevicesNode.ts).

## API and operational checks

Authenticated READONLY inspection / ADMIN mutation:

- GET/POST `/api/v1/rooms`; PUT/DELETE `/api/v1/rooms/{id}`
- GET `/api/v1/channels?identifier=...`; PATCH `/api/v1/channels/{id}`
- GET/PUT `/api/v1/modules/{identifier}/rooms`
- GET `/api/v1/modules/{identifier}/room-controls`
- GET `/api/v1/bridges`
- PUT `/api/v1/bridges/{mqtt|matter}/settings`

The shared channel editor appears on both module pages; Settings contains
Rooms and both bridge settings/status panels. Existing hardware intensity,
fade and maintenance controls remain in their established paths. Legacy channel
name/emergency writes update the authoritative registry transactionally.

Before deployment: verify tests, back up the installed PostgreSQL database to a
host-local protected file, restore a clone, apply migration 008 deliberately,
check preserved rows/constraints, retain the old image/container, and deploy the
exact tested release. Verify health, version, login route and new authenticated
metadata APIs. Preserve independent Heartbeat V3, PostgreSQL, watchdog, USB
storage, certificates and networking. Do not actuate outputs to validate this
feature. Follow the Jetson operations runbook.
