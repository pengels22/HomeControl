# HomeControl architecture rebuild audit

Status: source audit of `b1ef32db2ac870278f93a8371308818df9a4f379` (2026-10-22). This is a software inventory and change plan, not a claim of physical commissioning or Matter fabric acceptance. The pasted rebuild brief is a requested target architecture; current source and the white papers describe the installed baseline.

## Current ownership and dependency map

| Concern | Current authority and path | Consumers and constraints |
| --- | --- | --- |
| Modules and identity | `02_HCM/registry.py`, `08_servises/common/agent.py`, `09_database/schema.sql` | Framed authenticated module session; registration, configuration, state reports, and commands. `MODULE_TYPES` and SQL type checks currently enumerate RCM/LCM/SIM/PNL, so future types require deliberate registry, configuration, and migration work. RMC is a CAN node behind SIM; ACM has an independent firmware/state machine. |
| Output commands | `02_HCM/devices.py` -> `priority.py` -> shared `safety_arbiter.py` -> module registry | API, HVAC, rules, panel, MQTT, and Matter ultimately use logical binding arbitration. Reconnection blocks energizing commands until a state report is accepted; module agents hold outputs and retain local overrides during HCM loss. |
| Life safety | `02_HCM/safety.py`, `safety_relays.py`, `channel_registry.fire_shutdown`, shared arbitration, module local safety | Independent of Matter, weather, UI, and consumer providers. Maintenance lockout and fire priority, classified HVAC OFF, and emergency lighting require focused regression tests before any refactor. GPIO and physical output behavior remain unverified in hardware. |
| Locations | `rooms`, `room_hvac`, `channel_metadata.room_id`, `logical_devices.room_id`, `pnl_rooms`; `metadata_api.py` | Rooms are durable and used by HVAC, channels, and PNL. There is no HCM Area table or room-to-Area relationship. ACM Areas are separate firmware concepts and must remain so. |
| Channels and entities | `channel_metadata` (migration 008), `logical_devices`, `device_bindings`, `integrations.registry`/`entities` (migration 009) | Channel IDs are durable; logical names are the control boundary. Integration entities are provider-owned and are not a unified physical-module capability model. Do not merge or delete these tables without mapping ownership and foreign keys. |
| Matter | `02_HCM/bridges.py`, `08_servises/matter_bridge/bridge.mjs`, `matter_endpoints` | Optional Node child of HCM. PostgreSQL allocates stable endpoint numbers and retains tombstones; SDK storage holds fabric state when configured. Current mapping is LIGHTING relay/level only. On/Off and level commands call HCM `external_command`, which rechecks exposure, binding, safety, and logical arbitration. A child process exit currently leaves the bridge unavailable until settings change or HCM restarts. Real commissioning, multi-fabric behavior, IPv6/mDNS reachability, and restart identity have not been HIL verified. |
| Weather and time | `integrations/nws.py`, `integrations/weather.py`, `automation.SunCalculator`, `settings.timezone/latitude/longitude`, ACM time exchange | NWS is a provider instance, not an always-on native service. Its point metadata is process-memory only; forecast is daily subset, no hourly/current observation service, and alerts are not independently durable. Poll startup can fail, while runtime isolates providers from safety. Timezone and sun calculation exist; HCM has no consolidated native time/sync-status API. ACM's existing time delivery is protected. |
| Consumer integrations | `integrations/*`, `bridges.py` MQTT, HA import/staging/mapping modules, frontend | Provider runtime also hosts native helper/service/event facilities used by automation, zones, notifications, and other core-facing functions. Removal must follow dependency decoupling. Google, SmartThings, media, OpenAI, OWM, MQTT discovery, and HA importer are retirement candidates, not safe immediate deletions. |
| Admin UI | `02_HCM/www`, `api.py`, `metadata_api.py`, integration/automation APIs | Current navigation includes Dashboard, Devices & Services, integrations, HA mappings, automations, module tools, rooms, and bridge settings. The engineering/admin controls must survive simplification. |
| Deployment | `07_config/10_Common`, `11_scripts/hcm_docker_deploy.py`, Dockerfile, systemd units | Jetson HCM runs in Docker; PostgreSQL, host Heartbeat V3, watchdog, and ACM remain separate. Existing replacement retains a rollback container, but historical rollback/image cleanup must be proven before adding retention. No database migration runs automatically on startup. |

## Database and API impact

The schema currently has migrations 001-024. Migration 008 introduced channel metadata and `matter_endpoints`; 009-016 introduced provider/integration tables; 017-019 added automation and native primitives; 022 added zones; 023-024 added HA migration/provenance. A forward migration is required for HCM Areas and any new native weather/time persistence. Keep prior migrations and installed data intact. `schema_contract.py` must be updated whenever required tables or columns change, and an installed database needs a tested backup/clone migration path before deployment.

Canonical API building blocks already exist at `/api/v1/modules`, `/logical-devices`, `/rooms`, `/channels`, `/bridges`, safety and diagnostics routes. The bridge currently reads `channel_registry.channels()` internally. A new entity API should first project these authoritative rows, then let Matter consume the same service. Provider entities must remain distinguishable from physical channels. No direct bridge-to-module command path is acceptable.

## Retain, refactor, retire

- Retain unchanged during the first passes: safety/fire and physical drivers; HVAC sequencing; module protocol, identity, state reconciliation and local overrides; ACM firmware; Heartbeat V3/Conflict; PostgreSQL/auth/fault/update/rollback foundations.
- Refactor with compatibility: location model to add HCM Areas; canonical capability/state projection over channel and logical binding rows; Matter lifecycle and mappings; NWS and time as native HCM services; admin UI navigation.
- Retire only after import/API/DB/frontend/test callers are migrated: HA importer/staging/mapping, broad provider runtime, Google/SmartThings/OWM/OpenAI/media providers, generic OAuth, MQTT Home Assistant discovery, consumer dashboard and automation editor surfaces. Keep fire TTS/notification hooks and native policy/event functions where required.

## Primary risks and validation gates

1. A safety or reconciliation regression could energize outputs incorrectly. Keep command routing and module firmware behavior unchanged while building read-only canonical projections; add focused safety and reconnect tests for later changes.
2. Endpoint renumbering or lost SDK storage could duplicate accessories. Preserve `matter_endpoints` and fabric storage, and verify restart/recommission scenarios before claiming Matter acceptance.
3. New Area/weather/time schema cannot be deployed onto the older installed PostgreSQL database by container replacement alone. Apply only forward migrations after backup and clone testing.
4. Removing provider runtime now would break native primitives, automation, zones, notifications, and existing records. First extract these dependencies, preserve data, and deprecate consumer entry points explicitly.
5. CI software tests do not prove electrical fire input, module output, CAN, Matter network discovery, NWS service availability, or installed ACM behavior. HIL and production acceptance remain separate.

## Smallest coherent sequence

1. Add regression coverage and repair the existing Matter child lifecycle without changing endpoint assignment or safety routing.
2. Add a canonical read-only physical entity projection and HCM Area model through forward migration and authenticated API. Keep existing room/channel/bridge paths compatible.
3. Move Matter enumeration to that projection and expand only semantically valid device mappings; verify bidirectional state and stable identity against persistent storage.
4. Extract NWS and time from provider runtime with cached/degraded status and admin APIs. Keep ACM's existing synchronization path.
5. Simplify admin UI and retire consumer providers one dependency group at a time. Validate backups, migration, full CI, deployment rollback and hardware acceptance separately.

## Checkpoint 1 — Core Boundary / Areas / Entity Projection

Checkpoint reviewed on 2026-10-23. The working tree is uncommitted and has not been deployed. The base commit remains `b1ef32d`.

### Changes and compatibility

- `09_database/025_hcm_areas.sql` is a forward migration after 024. It adds `hcm_areas` and a nullable `rooms.area_id` with a restrictive foreign key. Existing Rooms do not need an Area. The API disables Areas instead of deleting them; direct SQL deletion of an assigned Area is blocked. ACM firmware Areas and alarm tables are untouched.
- `02_HCM/metadata_api.py`, `channel_registry.py`, `schema_contract.py`, and `www/app.js` add authenticated Area CRUD, optional Room assignment, location projection, and a basic admin editor. Existing Room PUT requests that omit `area_id` retain their current assignment. The new image requires migration 025 before startup because the schema contract and channel query include Areas; migration is not automatic.
- `02_HCM/entities.py` projects physical output channels from PostgreSQL metadata and the most recent module state report. It holds no separate state. It exposes stable `channel_<id>` identity, module ID/type, channel, name, capability, Room/Area, current reported command state, availability, reported faults, write eligibility, and Matter exposure. Unknown future channel kinds remain visible internally and are not coerced to a Matter dimmer. `GET /api/v1/entities` is authenticated and read-only. Current coverage is RCM/LCM physical output channels; sensors, ACM, HVAC virtual state, and provider entities need explicit canonical adapters later.
- `02_HCM/bridges.py` uses the canonical projection for shared state/location fields. Existing Matter endpoint allocation and Node storage are untouched; commands still call `external_command` and `devices.command_logical` through safety arbitration. Unexpected child exits retry with exponential backoff capped at five minutes. States distinguish disabled, missing configuration, starting, running, unexpected exit, repeated failure, and intentional stop. Disabled settings do not relaunch the process.
- Tests changed in `12_tests/test_channel_metadata.py`, `test_metadata_database.py`, and `test_db_migrations.py`. The migration regression applies the base schema and migrations 001–024 before 025, then verifies the old Room survives, its Area remains optional, and an assigned Area cannot be deleted. Tests cover Area API authorization, identity/rename stability, canonical projection, unsupported future Matter kinds, and Matter retry/disabled behavior.

### Review and validation

The diff contains no edits to fire/life safety, ACM firmware, GPIO/pinout/polarity, module agents, module protocol, or HCM reconciliation. Existing safety and reconciliation tests pass. The Matter command and persistent endpoint paths remain intact. This is code review and software regression evidence, not hardware or commissioned-fabric evidence.

Focused tests: **67 passed** before the final mapping correction; affected focused tests after correction: **62 passed**. Full PostgreSQL-backed Python suite: **849 passed, 1 skipped, 1 existing deprecation warning** on both the initial and final checkpoint runs. Python compileall, JavaScript syntax, Matter `npm run check`, Matter local endpoint validation, active configuration safety grep, and `git diff --check` passed. Docker image build was not run locally because Docker is unavailable in this workspace; hosted CI is pending a commit. No HIL test or live-host deployment was performed.

### Remaining risks and phases

- Migration 025 must be backed up, tested on an installed-database clone, applied deliberately, and verified before any HCM image containing this change is deployed. The live Jetson database has not been modified.
- Matter retry behavior is software-tested with a fake child; real process restart, commissioning persistence, controller behavior, and IPv6/mDNS remain to be validated in a controlled deployment.
- Phase A: extend canonical adapters for SIM/RMC sensor and future module capabilities without changing control authority. Phase B: expand semantically valid Matter mappings and prove stable identity. Phase C: native time service. Phase D: native NWS service and alert cache. Phase E: admin UI refocus. Phase F: dependency-led legacy integration retirement. Docker rollback retention and full HIL acceptance remain separate work.

## Checkpoint 2 — Canonical Entity/Capability Layer

Phase A completed on 2026-10-23. The entity layer remains a read-only projection over PostgreSQL channel metadata and the latest HCM module state report.

### Implementation

- `02_HCM/entities.py` normalizes RCM/LCM output channels and established SIM/RMC telemetry. Output capabilities include `relay`, `binary_switch`, `light`, and `dimmable_light`. RMC/SIM values map only when their source keys are present: temperature, humidity, illuminance, presence/occupancy, motion, contact, and generic analog inputs. Unknown channel or sensor sources remain internally representable with an explicit capability or `unknown`; they are not guessed into Matter types.
- Canonical entities include stable `entity_id`, module ID/type, source/channel, name, capability and capability list, Room/Area, current reported state, availability classification (`available`, `unavailable`, `faulted`, `unknown`, or `stale`), fault state, writable flag, Matter exposure preference, and source metadata. Sensor entities are always read-only. No live values are persisted by this layer.
- SIM/RMC state comes from the existing `modules.last_state` JSON updated by the module registry. A disconnected module produces unavailable entities while preserving its physical output behavior and last-known state in the existing module record. RMC sensor fault arrays and stale flags remain attached to the projected entity.
- `GET /api/v1/entities` supports filtering by module, Room, Area, capability, and availability. `GET /api/v1/entities/{entity_id}` retrieves one projection. Both are authenticated read-only API paths. They do not command modules; command routing remains in the existing logical device and safety arbitration path.
- Existing HCM Areas and nullable Room `area_id` are included in applicable projections. ACM alarm Areas are not queried, copied, or exposed as generic entities. PNL remains a consumer of the existing Room/lighting projection.

### Mapping boundaries

RCM exposes relay channel entities; LCM exposes relay and dimmer entities. SIM exposes established Hexa analog values and RMC telemetry received through its CAN state. RMC is represented through SIM's existing `rmc_nodes` state boundary. PNL exposes room control metadata and is not a physical sensor source. ACM remains an autonomous alarm controller; its internal sensors, alarm state machine, keypads, and relays are not generic writable HCM entities. HVAC remains on its existing semantic controller path; no new thermostat command path was added.

### Tests and validation

Added regression coverage for stable identities across rename/location changes, RCM/LCM output capability lists, SIM/RMC sensor units and source metadata, stale versus faulted state, unknown future channels, read-only sensor behavior, module and availability filtering, entity detail lookup, existing Rooms without Areas, and the absence of a projection command path. Focused entity/database tests pass: **64 passed**. Final Phase A full validation: **853 passed, 1 skipped, 1 warning**.

### Deferred work and limitations

Matter mappings for sensors, fault entities, thermostat state, and future capabilities are intentionally deferred to Phase B. Current sensor discovery is limited to established keys in SIM/RMC state; no semantics are invented for arbitrary CAN frames or ACM internals. Module capability registration remains the existing extensibility path and does not create entities until a source state mapping is defined. No live host deployment, database migration, hardware validation, or Matter commissioning was performed for Phase A.

## Checkpoint 3 — Matter Bridge

Phase B completed on 2026-10-23. Matter remains an adapter over canonical HCM projections. The bridge does not query module sockets, GPIO, or live-state tables directly.

### Architecture and mappings

- `02_HCM/bridges.py` now exposes a capability mapper registry consumed by the Matter projection. Lighting and dimming map to On/Off Light and Dimmable Light. Temperature, humidity, illuminance, occupancy/presence, motion, and contact have explicit mapper names for the Matter adapter. Generic relays, analog values, fault-only entities, unknown capabilities, and unsupported HVAC semantics remain internal unless a future semantic mapper is added.
- `08_servises/matter_bridge/bridge.mjs` consumes canonical `entity_id`, capability, state, availability, and endpoint fields. Sensor values are converted at the adapter boundary: Fahrenheit to Matter hundredths of Celsius, relative humidity to hundredths of a percent, and lux to the Matter logarithmic illuminance encoding. Sensor entities are read-only. Commands retain the existing channel ID only as an HCM command-path reference.
- HCM-to-Matter synchronization is driven by every registry refresh, so module reports, local overrides, admin commands, safety actions, and reconnect reconciliation flow through the canonical projection before Matter attributes are updated. Matter commands still call `external_command`, logical-device arbitration, and the existing safety checks.

### Identity, lifecycle, and persistence

- Existing `matter_endpoints` allocation remains the endpoint source of truth. It is keyed to the stable channel entity identity (`channel_<channel_metadata.id>`) and allocates monotonically; endpoint numbers are not derived from enumeration order. Rename, Room/Area changes, reconnects, restarts, and unrelated additions therefore do not renumber existing endpoints.
- Existing endpoint tombstones remain reserved when a channel is deleted (`ON DELETE SET NULL`); the allocator never reuses those numbers. Sensor endpoint persistence is intentionally not enabled by default because Phase A sensor entities have no administrative Matter exposure flag or endpoint allocation record yet.
- Existing Matter.js storage is still selected by `HCM_MATTER_STORAGE`, with the stable server ID `homecontrol`. Fabric/commissioning data is therefore host-mounted and survives bridge/HCM restart and software replacement when that directory is retained. It is not returned by HCM APIs or normal logs. Backup of that directory remains an operator responsibility.
- The Python bridge lifecycle retains disabled, not-configured, starting, running, unexpected-exit, bounded retry, repeated failure, and intentional-stop states. Exponential retry is capped at five minutes and intentional stop/disabled configuration suppresses relaunch.

### Files and tests

Changed `02_HCM/bridges.py`, `08_servises/matter_bridge/bridge.mjs`, `12_tests/test_channel_metadata.py`, and this audit. Added mapper registry tests for supported capabilities and explicit unsupported analog/generic relay behavior. Matter validate-only startup now instantiates light, dimmable-light, and temperature sensor mappings.

Phase B focused validation: **73 passed**; full pytest: **862 passed, 1 skipped, 1 warning**; Matter `npm run check` passed; Matter validate-only startup passed with light, dimmable-light, temperature, humidity, illuminance, occupancy, and contact mappings; Python compileall, JavaScript syntax validation, active configuration safety checks, and `git diff --check` passed.

### Known limitations and remaining HIL

Sensor administrative exposure and persistent sensor endpoint allocation remain deferred because the current database exposure setting is channel-only. Contact polarity is taken from canonical HCM state and is not inferred from GPIO. True Matter controller interoperability, multi-fabric commissioning, bridge/HCM restart with an already commissioned controller, mDNS/IPv6 behavior, physical sensor transitions, safety override observation, and reconnect hardware behavior still require controlled HIL testing. Time, NWS, UI refocus, and legacy integration retirement were not started.

## Checkpoint 4 — Native Time Service

Phase C completed on 2026-10-23. The repository audit found direct wall-clock calls across module telemetry, heartbeat, management, safety, integrations, scripts, and legacy provider code; existing monotonic timers remain in safety, HVAC, retry, heartbeat, and UI paths. HCM already had a narrow ACM `TIME_REQUEST`/`TIME_RESPONSE` exchange, while automation and primitives separately accepted configured timezone names. No shared HCM time API or synchronization-health model existed.

### Service architecture

- `02_HCM/time_service.py` provides the canonical application interface: timezone-aware `now_utc()`, `now_local()`, `local_date()`, configured `timezone()`, UTC offset, DST state, and a monotonic helper. It uses the host clock and never maintains or advances a software clock. An injected clock and synchronization probe make wall-clock tests deterministic.
- The configured timezone is sourced from `HCM_TIMEZONE` through `settings.timezone`, with the installation default `America/Detroit`. `zoneinfo.ZoneInfo` performs EST/EDT conversion and date-boundary handling; persisted machine timestamps remain governed by their existing UTC/database semantics.
- Synchronization health is best-effort and cached for 30 seconds. The service probes Linux `timedatectl` for NTP synchronization when available and returns `synchronized`, `unsynchronized`, or `unknown`. Probe failure never removes access to system time and never exposes raw shell output.
- `GET /api/v1/time` is an authenticated, read-only administrative endpoint exposing UTC, local timestamp, timezone, offset, DST, synchronization state, source/detail, and health check time. Internal components use the Python service directly rather than the HTTP endpoint.
- ACM time bootstrap now obtains UTC through the canonical service while preserving the existing `TIME_RESPONSE` wire format and the HCM→ACM→keypad authority chain. No ACM state machine, keypad behavior, module protocol, or safety timing was changed.

### Files and validation

Changed `02_HCM/time_service.py`, `02_HCM/settings.py`, `02_HCM/api.py`, `02_HCM/registry.py`, `12_tests/test_time_service.py`, `12_tests/test_api.py`, and this audit. Tests cover injected UTC, EST and EDT conversion, local date boundaries, sync states and caching, unknown telemetry, aware API output, invalid zones, and the administrative API.

Focused time/API tests: **23 passed**. Full pytest: **868 passed, 1 skipped, 1 warning**. Python compileall, JavaScript syntax validation, Matter bridge validation, Matter validate-only startup, active configuration safety checks, and `git diff --check` passed.

### Known limitations and deployment/HIL

The service reports host synchronization telemetry only when the deployed Linux image provides usable `timedatectl` output; otherwise it reports `unknown` while continuing to provide system time. Existing direct time calls were intentionally not mass-refactored, and protected safety/heartbeat timing remains unchanged. ACM live time exchange, host NTP status, reboot behavior, and installed keypad display behavior still require deployment/HIL verification. NWS, frontend refocus, and legacy integration retirement were not started.

## Checkpoint 5 — Native NWS Weather Service

Phase D completed on 2026-10-23. The previous NWS implementation was a generic provider-runtime instance that published a limited forecast and alert count through provider entities. Its point metadata was process-memory only, current observations were not fetched separately, forecast periods were bounded but not split into native hourly/daily resources, and no native weather health/cache API existed. Existing provider registration and compatibility paths remain in place.

### Native architecture

- `02_HCM/weather_service.py` is a standalone, failure-isolated NWS service using the Phase C `TimeService` for all timestamps, age calculations, UTC normalization, and expiration-safe comparisons. It uses configured HCM latitude/longitude and never replaces physical HCM sensor entities.
- Point lookup resolves and caches forecast office, grid coordinates, forecast URLs, county/zone, and observation-station collection links. A bounded JSON cache under the configured HCM storage root survives process restarts without persisting raw unbounded NWS responses.
- Current observations are normalized separately from forecasts, retaining observation time, temperature and unit, humidity, dew point, wind, pressure, visibility, description, station, and data age. Hourly and daily NWS periods remain separate timezone-aware normalized records with start/end, temperature, precipitation probability, wind, descriptions, and day/night state.
- Active alerts retain NWS identity and supplied event, headline, severity, urgency, certainty, status, message type, timestamps, area, description, instructions, sender, response, and parameters. Repeated alerts are deduplicated; new, changed, and removed alerts emit `weather.alert.new`, `weather.alert.updated`, and `weather.alert.expired` through the optional HCM event sink.
- Resource refreshes are independent. Point, current, daily, hourly, and alerts failures are isolated; cached values remain visible with explicit `healthy`, `degraded`, or `unavailable` health and last-success/attempt/error metadata. Startup launches the service task without waiting for Internet, DNS, or NWS availability. Polling is bounded by configured intervals and HTTP timeout behavior.

### API and compatibility

Authenticated read-only APIs are provided at `/api/v1/weather`, `/current`, `/hourly`, `/forecast`, `/alerts`, and `/health`. The top-level summary includes condition, temperature, humidity, active alert count, highest NWS severity, health, and update time. The old `NWSProvider` and provider runtime remain registered for existing automation/provider consumers; retirement or redirection is deferred to the legacy-integration phase. Existing `SunCalculator` remains local and independent of NWS.

### Files and validation

Changed `02_HCM/api.py`, `02_HCM/main.py`, `02_HCM/weather_service.py`, `12_tests/test_weather_service.py`, and this audit. Focused weather/API tests: **23 passed**. Full pytest: **873 passed, 1 skipped, 1 warning**. Python compileall, JavaScript syntax validation, Matter bridge validation, Matter validate-only startup, active configuration safety checks, and `git diff --check` passed.

### Known limitations and deployment requirements

No weather database migration was added; the bounded cache is filesystem-backed and may be unavailable until the configured storage root is writable. NWS unit fields are preserved as source units rather than globally converted. No live NWS calls, Internet dependency, frontend work, notification UI, weather Matter accessory, or production deployment was performed. Live NWS rate-limit behavior, station selection, cache recovery after reboot, and installed-host filesystem permissions require deployment verification. Fire/life-safety, ACM, module protocols, heartbeat, Matter mappings, and Time Service semantics were not changed.

## Checkpoint 6 — Admin UI Refocus

Phase E completed on 2026-10-23. The former primary navigation presented Dashboard, Devices & Services, Automations, Helpers, Settings, and Users, with consumer/provider-oriented surfaces mixed into the main path. The frontend already contained useful module commissioning, safety, bridge, room, and diagnostics views, so this phase refocused navigation and added native engineering views without deleting legacy backend or UI compatibility paths.

### New information architecture

Primary navigation now centers on System Overview, Modules, Entities / Channels, Rooms / Areas, Matter, Weather, Time, Safety, Diagnostics, and Administration. Automations, legacy Devices & Services, and Users remain accessible as secondary administration links. Existing device detail, module role, channel configuration, safety, bridge settings, update, authentication, HA mapping, and automation routes remain available.

### Native admin surfaces

- Entities / Channels uses `/api/v1/entities` and presents canonical entity identity, module/source, capability, Room/Area, state, availability, writable/read-only status, and Matter exposure.
- Rooms / Areas uses `/api/v1/areas` and `/api/v1/rooms`, explicitly preserves Rooms without Areas, and distinguishes HCM Areas from ACM alarm Areas.
- Matter uses `/api/v1/bridges` to show bridge lifecycle, mapped/unsupported counts, persistent endpoints, and exposure status without fabric secrets.
- Weather uses the native `/api/v1/weather*` APIs for service health, current conditions, cache age, forecast availability, and NWS alert severity/urgency/certainty. It does not use provider entities as its authority.
- Time uses `/api/v1/time` for UTC/local time, timezone, offset, DST, and synchronization status.
- Safety remains read-only in the new page and uses existing `/api/v1/safety/status` and `/api/v1/health` data. No unsafe convenience controls were added. Diagnostics retains existing live HCM service and safety relay status.

### Compatibility and validation

Changed `02_HCM/www/index.html`, `02_HCM/www/app.js`, `02_HCM/main.py`, and this audit. Existing legacy integrations, provider pages, HA mapping, automation backend, and module communication remain present and are not removed in Phase E. Frontend error handling continues to show unavailable/degraded states rather than inventing fresh values. Full pytest: **873 passed, 1 skipped, 1 warning**. Preview/frontend route tests: **38 passed**. JavaScript syntax validation, Python compileall, Matter bridge validation, Matter validate-only startup, active configuration safety checks, and `git diff --check` passed.

### Known limitations

The new admin pages are observability and commissioning views; advanced inline editing remains on the existing Settings and module pages. Overview still retains selected existing HCM diagnostics cards, while the new pages provide the native service-specific status views. Legacy UI surfaces are de-emphasized but not deleted pending Phase F dependency review. No browser/device HIL, production deployment, or external Matter/NWS connectivity was performed.

## Checkpoint 7 — Dependency-Led Legacy Integration Retirement

Phase F completed on 2026-10-23 after an import and runtime-reference audit. Retirement was deliberately staged because the generic integration runtime still hosts core HCM functionality.

### Classification

| Component | Classification | Reason |
|---|---|---|
| `integrations/runtime.py`, `registry.py`, `services.py`, `events.py` | CORE DEPENDENCY | Automation, zones, device events, native primitives, notifications, and service declarations still use these modules. |
| `integrations/http.py`, secrets/auth primitives | KEEP | Native NWS and administrative infrastructure use bounded HTTP or authentication primitives. |
| Native `02_HCM/weather_service.py` | KEEP | Authoritative weather service. |
| Old `integrations/nws.py` | COMPATIBILITY-ONLY | Existing provider consumers/tests may still import it; native NWS is now authoritative. |
| OWM, Google, SmartThings, OpenAI, Denon, HEOS providers | COMPATIBILITY-ONLY | Retained importable for historical data, direct tests, and rollback compatibility, but no longer loaded by normal HCM startup. |
| `integrations/oauth.py` and provider credential storage | COMPATIBILITY-ONLY | Only consumer-provider configuration paths use these; HCM user authentication is separate and retained. |
| HA importer/staging/mapping modules and migration tables | COMPATIBILITY-ONLY | Historical migration records and review APIs remain available; no runtime execution path was removed blindly. |
| Existing integrations API/config API and legacy UI routes | COMPATIBILITY-ONLY | Existing callers and historical configuration remain supported while Phase F establishes a safe retirement boundary. |
| Module registry, canonical entities, Rooms/Areas, safety, Matter, Time, weather, automation/policy | KEEP / CORE DEPENDENCY | Protected HCM operation. |

### Change made

`02_HCM/main.py` no longer imports or registers consumer providers (OWM, Google, SmartThings, OpenAI, Denon, HEOS) during normal startup. Native NWS and the local iBeacon provider remain available where explicitly required. Existing provider source files, database rows, OAuth records, HA migration data, APIs, and tests remain intact for compatibility and rollback; they are not foundational to the active HCM startup path.

The Phase E legacy UI links remain secondary rather than being deleted because their backend compatibility surfaces still exist. No provider-owned entities were merged into canonical HCM entities. The automation engine, event bus, notification hooks, and service declarations were preserved because core code still depends on them. No fire/life-safety, module protocol, heartbeat, Matter, Time, Weather, or database migration semantics were changed.

### Validation

Full pytest: **873 passed, 1 skipped, 1 warning**. Preview/frontend tests: **38 passed**. Python compileall, JavaScript syntax validation, Matter bridge validation, Matter validate-only startup, active configuration safety checks, and `git diff --check` passed.

### Remaining retirement work

Provider modules can be deleted only after a separate dependency review confirms no rollback, direct API, migration, or operator tooling requires them. HA migration tables should remain for historical provenance. Generic runtime extraction, provider-owned entity retirement, and legacy UI deletion remain follow-up work; this checkpoint does not claim the consumer framework is fully removed.
