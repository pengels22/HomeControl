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
