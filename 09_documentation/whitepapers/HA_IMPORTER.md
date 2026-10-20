# Home Assistant Compatibility Analyzer and Importer V1

HCM accepts exported `automations.yaml`, `scripts.yaml`, and `scenes.yaml` (or
equivalent list/mapping fragments). The importer has two explicit phases:

1. **Analyze** parses with `yaml.safe_load`, normalizes old and new HA keys,
   inspects nested features and references, and returns a serializable preview.
   It does not connect to HA, execute actions, read paths, or mutate HCM.
2. **Apply** accepts a reviewed plan and selected eligible items. It re-analyzes
   the source, uses native HCM validation/stores, and creates automations disabled.
   Scripts and scenes are created without running them. `dry_run` performs all
   checks and creates nothing.

Every item and nested element receives one of `COMPATIBLE`, `TRANSLATED`,
`NEEDS_MAPPING`, `UNAVAILABLE_SERVICE`, or `UNSUPPORTED`. Item eligibility is
`READY`, `READY_WITH_TRANSLATIONS`, `BLOCKED_MAPPING`, `BLOCKED_SERVICE`, or
`BLOCKED_UNSUPPORTED`; unsupported nested behavior is never silently removed.

The analyzer preserves sanitized source, source type/id/index, alias, a
deterministic source fingerprint, referenced entities/services, warnings,
unsupported elements, and a normalized native preview. Secret-like fields are
redacted in reports. YAML size and nesting are bounded and unsafe tags are
rejected by the safe loader.

Entity mappings are explicit (`source entity_id` to immutable HCM `entity_ref`),
with exact, suggested, unresolved, and ambiguous outcomes represented through
the mapping result. Device and area targets require an explicit mapping; fuzzy
name matching is not authoritative. Service compatibility is defined in the
data-driven `SERVICE_MAPPINGS` registry. Native services are used in previews;
provider handlers are never called directly.

State, numeric-state, time, time-pattern, sun, event, manual, boolean, template,
delay, variables, stop, service, scene, script, if, choose, bounded repeat, and
parallel forms are inspected. Zone and conversation triggers, unbounded waits or
repeats, arbitrary shell/python execution, and unresolved device triggers are
reported rather than fabricated. Templates are compiled by the bounded HCM
Expression Engine; Jinja control blocks remain unsupported.

The native runtime provides translated targets for `if`, `choose`, bounded
`repeat`, bounded `parallel`, `wait_template`, `wait_for_trigger`, numeric-state
triggers, and `automation.turn_on`/`turn_off`/`trigger`. These mappings do not
override remaining entity, climate, notification, zone, conversation, or
security-service blockers; an item remains blocked until every nested requirement
is eligible.

Media actions use the generic `media_player` contract. `play_media` flattens HA's
`media` object into bounded `media_content_id`, `media_content_type`, `metadata`,
and `enqueue` arguments; HEOS favorite IDs remain provider data. Existing power,
volume, source, and playback controls map to the corresponding generic service.
`heos.group_volume_up/down` translate to generic volume operations. Mobile
`notify.*` services translate to `notify.send`, and `tts.cloud_say`/`tts.speak`
translate to `announcement.speak`, but both retain `NEEDS_MAPPING` until an HCM
destination/backend is configured. Unknown notification destinations are not
wildcard-mapped. TTS target fields are normalized to explicit media-player target
references and are never treated as durable HA identities.

Analyzer mappings may explicitly supply
`notification_destination:<source service>` and
`speech_backend:<source service or TTS entity>` UUID values. Without them, the
semantic service is recognized but remains `NEEDS_MAPPING`; with them, the
runtime definition carries only the immutable native UUID. A configured
destination/backend can still report an unavailable health state at runtime,
which is distinct from missing import mapping.

The preview endpoint can optionally enrich this offline plan with the native
Service Registry when HCM is running. Enrichment is read-only: it validates each
mapped target and operation, caches repeated checks, and uses bounded concurrent
requests. Results distinguish `SUPPORTED`, `SUPPORTED_BUT_UNAVAILABLE`, missing
services, missing targets, target capability mismatches, and invalid arguments.
Those capability results are folded back into the normal item eligibility while
leaving the pure `analyze_home_assistant` function deterministic and offline.
Unmapped targets, notification destinations, and dynamic template destinations
are marked `NOT_CHECKED`; they require mapping or their dedicated registry at
apply/runtime time. Apply re-analysis remains authoritative and never invokes a
provider during analysis.

Climate actions use the native logical HVAC contract: `climate.set_temperature`,
`climate.set_hvac_mode`, and `climate.turn_off` translate to HCM climate
services and still require an explicit entity mapping. `climate.turn_on` and
other HVAC-specific services remain unavailable until their semantics are
measured and approved.

HA device constructs are migration-only input. The analyzer resolves supported
device forms into ordinary HCM state triggers, state conditions, and Service
Registry calls; no device automation blob is retained in the native preview.
Opaque HA entity and device IDs remain unresolved until an exact mapping is
provided. Optional read-only entity/device/area registry exports may be supplied
as JSON data to normalize opaque entity IDs; paths, auth storage, and live HA
connections are not accepted. Suggested or ambiguous mappings remain blocked,
and deleted targets are not retargeted by name. ZHA button events, alarm/lock
controls, and other security-sensitive semantics remain deferred to dedicated
passes.

Zone/geofence constructs translate to the native trigger shape
`{type: "zone", tracker_ref, zone_ref, event}`. HA `platform: zone` and
device-form tracker `enters`/`leaves` use this same representation; tracker and
zone references remain blocked until exact mappings are supplied. Zone
conditions use `{type: "zone", tracker_ref, zone_ref}` and share native
membership state. The real-source audit measured 16 platform zone triggers, 4
device-form tracker enter/leave triggers, 3 zone conditions, 9 unique zones,
and 5 tracker entity references. No real coordinates are included in previews,
fixtures, or reports. Native zone definitions are stored by migration 022;
tracker×zone membership remains transient and is rebuilt without startup events.

Measured ZHA device triggers translate through the semantic registry: short press
becomes `device_event` category `button`, action `press`; double press becomes
`double_press`; long press becomes `hold`, with the source subtype retained as a
bounded button identifier. The three source device IDs require explicit
`device:<ha_device_id>` mappings. Unknown ZHA commands, including the separate
`zha_event` `device_offline` diagnostic trigger, remain unsupported. No raw ZHA
payload is retained in the native trigger contract.

Endpoints:

- `POST /api/v1/import/home-assistant/analyze` (ADMIN): YAML fields or structured
  `sources`, plus optional mappings.
- `POST /api/v1/import/home-assistant/apply` (ADMIN): reviewed plan, selected
  item IDs, mappings, and optional `dry_run`.

No live Home Assistant connection or filesystem path is accepted. Provenance is
returned with every applied item (`home_assistant`, source type/id/fingerprint),
and source content is never overwritten. Durable plan/history storage and update
merging can be added in a later migration once the review workflow is exercised.
### Real configuration expression audit

The measured audit of the disposable real source set (125 automations, 7
scripts, 4 scenes) is analysis-only. Of 74 template-bearing values, 33 are
currently compatible with HCM's bounded expression engine and 41 remain
blocked or intentionally unsupported. V1 adds only safe filter-chain
normalization and `none` tests; control blocks, random selection, collection
queries, and arbitrary Jinja remain deferred. Reports redact source values and
are not committed.

### Semantic service completion V1

The authoritative pre-pass analyzer totals are 0 `READY`, 1
`READY_WITH_TRANSLATIONS`, 81 `BLOCKED_MAPPING`, 23 `BLOCKED_SERVICE`, and 31
`BLOCKED_UNSUPPORTED`. The unique service inventory is measured from the real
source (counts are occurrences): notifications (51), automation controls (39),
lighting (28), climate set/mode/off/on (29), media controls (38), helper
services (29), alarm controls (10), scene/script services (10), timers (5),
system/homeassistant lifecycle (5), update (2), shell command (2), todo (1),
and weather forecast reads (1). Source arguments and target forms are retained
only in the disposable sanitized report.

This pass adds the provider-neutral `weather.get_forecast` service and maps HA
`weather.get_forecasts` to it. NWS and OpenWeatherMap register the same bounded
read operation; responses contain at most 48 normalized forecast records and
use the normal `response_variable` path. Provider/backend unavailability is
reported without fabricated data.

`number.set_value` and `select.select_option` remain deferred because the real
targets are provider-owned and no generic writable-number/select capability is
currently registered. `climate.turn_on` remains deferred: the current HVAC
state has no persisted last non-off/default mode, so inventing one would be
unsafe. Alarm and lock mutation is safety/security-sensitive; shell commands,
system/update control, todo/list operations, and dynamic `scene.create` remain
separate subsystem or intentionally unsupported work. No HA-specific runtime
service or arbitrary process execution was added.

### Native security alarm semantics V1

The real source contains 10 alarm service calls across 9 source items: arm home
(3), arm away (2), arm vacation (3), and disarm (2). Every call includes a
literal code; the audit records only `code_present: true` and `code_form:
literal`. No alarm triggers, alarm conditions, lock actions, or security
notification actions were found in the measured source set.

HCM now exposes a provider-neutral `SecurityAlarmLayer` with canonical states
`disarmed`, `arming`, `armed_home`, `armed_away`, `armed_vacation`, `pending`,
`triggered`, and `unavailable`; canonical arm modes are home, away, and
vacation. Requests are serialized, capability-checked, policy-gated, and
delegated to a controller. A deterministic mock controller is test-only.
Disarm from an automation is denied by default; disarm requires a configured
credential reference when the controller requires one. Request results expose
credential presence only, never credential values or resolved secret material.

HA alarm services translate to native semantic services while source codes are
removed from runtime service data. Without an explicit
`alarm_credential:<target>` mapping, an item remains blocked with
`SECURITY_CREDENTIAL_MAPPING_REQUIRED` and `security_review_required`. Fire and
life-safety authority, GPIO, relay handling, maintenance lockout, and HVAC fire
shutdown are unchanged and remain separate from burglary/security state.

### Writable controls and safe service cleanup V1

The measured source forms are: `number.set_value` (3 calls in 3 items, static
`value` and entity targets), `select.select_option` (1 call in 1 item, static
`option` and a device target), `automation.toggle` (1 call in 1 item), and
`system_log.write` (2 calls in 2 items using `message`, `level`, and optional
`logger`). Neither measured number nor select argument used a template. The
two entity lifecycle calls were `homeassistant.update_entity` (2) and
`homeassistant.reload_config_entry` (1), both with entity targets.

Writable numbers and selects now have provider-neutral argument/capability
contracts. Providers opt in by registering the semantic service against their
owned entity; domain names alone do not imply writability. Number validation
enforces numeric type, declared bounds, and declared step without clamping.
Select validation rejects options not currently advertised. Existing
`input_number` and `input_select` helper services remain separate and unchanged.

`automation.toggle` is registered beside `turn_on` and `turn_off`, uses the
existing scheduler cleanup behavior, does not trigger an automation when
enabling it, and serializes the read/change operation. `system_log.write` maps
to bounded native `system.log` with debug/info/warning/error levels, bounded
message/category fields, dry-run support, and secret-like message redaction.
It cannot configure loggers, files, subprocesses, or system destinations.

Entity refresh and integration reload remain deferred: current providers own
their polling and lifecycle and no generic safe refresh/reload semantic is
available. Climate turn-on, software updates, shell commands, todo/list
operations, dynamic scenes, and conversation remain intentionally deferred.
