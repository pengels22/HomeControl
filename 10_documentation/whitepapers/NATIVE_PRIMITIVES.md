# Native Helpers, Scripts, and Scenes

HCM native primitives use the internal `hcm_native` provider only as an
ownership boundary. Definitions are durable in migration 019; state and
availability remain ordinary integration entities and durable entity events.
No primitive writes GPIO or calls a third-party provider directly.

Helpers include `input_boolean`, `input_button`, `input_number`, `input_text`,
`input_select`, `input_datetime`, `counter`, `timer`, and weekly `schedule`.
Their mutation services are registered through the normal Service Registry and
are virtual (`physical_mutation=false`). Timer state and expected finish are
persisted in entity attributes. Active timers are reconstructed after restart,
finish once if their deadline passed while HCM was offline, and paused timers
remain paused. Schedule helpers compute their next weekly transition in the HCM
timezone and own one cancellable task.

Scripts reuse the Automation action runner, modes, expression context, traces,
and run limits. Typed primitive inputs support required/default/type/options
validation. Script runs use the shared run table with `run_kind=script`, expose
`script.run`, and cap nested calls at five levels. Interrupted runs do not
resume after restart. Script calls use the normal service path.

Scenes store deterministic target entity references and desired state/attributes.
Snapshot scenes capture current normalized state and can be activated through
`scene.turn_on`; each target reports success or failure so partial results are
visible. Scene activation resolves ownership and invokes semantic services; it
does not mutate provider state directly. Static scene expression templating,
full domain-specific attribute translation, and importer/UI work remain future
phases.

Authenticated APIs expose `/api/v1/helpers`, `/api/v1/scripts`, and
`/api/v1/scenes`. READONLY users inspect; ADMIN users mutate, run scripts, and
activate scenes. Deletion rejects helper references from automations and native
entity deletion is restricted by the database.

## Scene translation and references

Scene activation uses a domain translator that inspects the target's registered
semantic services before planning operations. Switches and helper values use
`turn_on/off`, `set_value`, `select_option`, or `set_datetime`; lights use
`turn_on/off` and `set_level` for the canonical brightness value when that
service is registered; media players use power, normalized `volume_level`,
mute/unmute, and source services when available. Sensor-like domains,
`input_button`, timers, and schedules are reported as skipped/read-only.
Unsupported attributes and unavailable or missing targets are returned per target
and produce a partial result. Dry-run returns the same plan without invoking a
service.

Snapshots retain only restorable state: supported helper state, light
brightness, and media power/volume/mute/source. They never store availability,
provider metadata, diagnostics, media metadata, or secrets. Targets are
immutable `entity_ref` values, so entity display-ID renames do not break a
scene. Snapshot activation is best-effort and never writes provider-owned state
directly.

Reference inspection is derived from durable automation, script, and scene JSON
and expression dependencies. `GET /api/v1/references/entity/{entity_ref}` and
`GET /api/v1/references/{kind}/{id}` report source, source ID,
and definition path. Primitive deletion rejects known references with a
sanitized dependency summary; no dependent definition is rewritten.

| Domain | Restorable scene state |
|---|---|
| switch | on/off |
| light | on/off, brightness when `set_level` exists |
| media_player | power, normalized volume, mute, source when services exist |
| input_boolean/number/text/select/datetime/counter | native state service |
| sensor/binary_sensor/weather/calendar/device_tracker | skipped/read-only |
| input_button/timer/schedule | excluded from snapshots |
