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

Climate actions use the native logical HVAC contract: `climate.set_temperature`,
`climate.set_hvac_mode`, and `climate.turn_off` translate to HCM climate
services and still require an explicit entity mapping. `climate.turn_on` and
other HVAC-specific services remain unavailable until their semantics are
measured and approved.

Endpoints:

- `POST /api/v1/import/home-assistant/analyze` (ADMIN): YAML fields or structured
  `sources`, plus optional mappings.
- `POST /api/v1/import/home-assistant/apply` (ADMIN): reviewed plan, selected
  item IDs, mappings, and optional `dry_run`.

No live Home Assistant connection or filesystem path is accepted. Provenance is
returned with every applied item (`home_assistant`, source type/id/fingerprint),
and source content is never overwritten. Durable plan/history storage and update
merging can be added in a later migration once the review workflow is exercised.
