# HomeControl architecture rebuild audit

Status: source audit of `b1ef32db2ac870278f93a8371308818df9a4f379` (2026-10-22). This is a software inventory and change plan, not a claim of physical commissioning or Matter fabric acceptance. The pasted rebuild brief is a requested target architecture; current source and the white papers describe the installed baseline.

## Current ownership and dependency map

| Concern | Current authority and path | Consumers and constraints |
| --- | --- | --- |
| Modules and identity | `01_HCM/registry.py`, `08_servises/common/agent.py`, `09_database/schema.sql` | Framed authenticated module session; registration, configuration, state reports, and commands. `MODULE_TYPES` and SQL type checks currently enumerate RCM/LCM/SIM/PNL, so future types require deliberate registry, configuration, and migration work. RMC is a CAN node behind SIM; ACM has an independent firmware/state machine. |
| Output commands | `01_HCM/devices.py` -> `priority.py` -> shared `safety_arbiter.py` -> module registry | API, HVAC, rules, panel, MQTT, and Matter ultimately use logical binding arbitration. Reconnection blocks energizing commands until a state report is accepted; module agents hold outputs and retain local overrides during HCM loss. |
| Life safety | `01_HCM/safety.py`, `safety_relays.py`, `channel_registry.fire_shutdown`, shared arbitration, module local safety | Independent of Matter, weather, UI, and consumer providers. Maintenance lockout and fire priority, classified HVAC OFF, and emergency lighting require focused regression tests before any refactor. GPIO and physical output behavior remain unverified in hardware. |
| Locations | `rooms`, `room_hvac`, `channel_metadata.room_id`, `logical_devices.room_id`, `pnl_rooms`; `metadata_api.py` | Rooms are durable and used by HVAC, channels, and PNL. There is no HCM Area table or room-to-Area relationship. ACM Areas are separate firmware concepts and must remain so. |
| Channels and entities | `channel_metadata` (migration 008), `logical_devices`, `device_bindings`, `integrations.registry`/`entities` (migration 009) | Channel IDs are durable; logical names are the control boundary. Integration entities are provider-owned and are not a unified physical-module capability model. Do not merge or delete these tables without mapping ownership and foreign keys. |
| Matter | `01_HCM/bridges.py`, `08_servises/matter_bridge/bridge.mjs`, `matter_endpoints` | Optional Node child of HCM. PostgreSQL allocates stable endpoint numbers and retains tombstones; SDK storage holds fabric state when configured. Current mapping is LIGHTING relay/level only. On/Off and level commands call HCM `external_command`, which rechecks exposure, binding, safety, and logical arbitration. A child process exit currently leaves the bridge unavailable until settings change or HCM restarts. Real commissioning, multi-fabric behavior, IPv6/mDNS reachability, and restart identity have not been HIL verified. |
| Weather and time | `integrations/nws.py`, `integrations/weather.py`, `automation.SunCalculator`, `settings.timezone/latitude/longitude`, ACM time exchange | NWS is a provider instance, not an always-on native service. Its point metadata is process-memory only; forecast is daily subset, no hourly/current observation service, and alerts are not independently durable. Poll startup can fail, while runtime isolates providers from safety. Timezone and sun calculation exist; HCM has no consolidated native time/sync-status API. ACM's existing time delivery is protected. |
| Consumer integrations | `integrations/*`, `bridges.py` MQTT, HA import/staging/mapping modules, frontend | Provider runtime also hosts native helper/service/event facilities used by automation, zones, notifications, and other core-facing functions. Removal must follow dependency decoupling. Google, SmartThings, media, OpenAI, OWM, MQTT discovery, and HA importer are retirement candidates, not safe immediate deletions. |
| Admin UI | `01_HCM/www`, `api.py`, `metadata_api.py`, integration/automation APIs | Current navigation includes Dashboard, Devices & Services, integrations, HA mappings, automations, module tools, rooms, and bridge settings. The engineering/admin controls must survive simplification. |
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
- `01_HCM/metadata_api.py`, `channel_registry.py`, `schema_contract.py`, and `www/app.js` add authenticated Area CRUD, optional Room assignment, location projection, and a basic admin editor. Existing Room PUT requests that omit `area_id` retain their current assignment. The new image requires migration 025 before startup because the schema contract and channel query include Areas; migration is not automatic.
- `01_HCM/entities.py` projects physical output channels from PostgreSQL metadata and the most recent module state report. It holds no separate state. It exposes stable `channel_<id>` identity, module ID/type, channel, name, capability, Room/Area, current reported command state, availability, reported faults, write eligibility, and Matter exposure. Unknown future channel kinds remain visible internally and are not coerced to a Matter dimmer. `GET /api/v1/entities` is authenticated and read-only. Current coverage is RCM/LCM physical output channels; sensors, ACM, HVAC virtual state, and provider entities need explicit canonical adapters later.
- `01_HCM/bridges.py` uses the canonical projection for shared state/location fields. Existing Matter endpoint allocation and Node storage are untouched; commands still call `external_command` and `devices.command_logical` through safety arbitration. Unexpected child exits retry with exponential backoff capped at five minutes. States distinguish disabled, missing configuration, starting, running, unexpected exit, repeated failure, and intentional stop. Disabled settings do not relaunch the process.
- Tests changed in `12_tests/test_channel_metadata.py`, `test_metadata_database.py`, and `test_db_migrations.py`. The migration regression applies the base schema and migrations 001–024 before 025, then verifies the old Room survives, its Area remains optional, and an assigned Area cannot be deleted. Tests cover Area API authorization, identity/rename stability, canonical projection, unsupported future Matter kinds, and Matter retry/disabled behavior.

### Review and validation

The diff contains no edits to fire/life safety, ACM firmware, GPIO/pinout/polarity, module agents, module protocol, or HCM reconciliation. Existing safety and reconciliation tests pass. The Matter command and persistent endpoint paths remain intact. This is code review and software regression evidence, not hardware or commissioned-fabric evidence.

Focused tests: **67 passed** before the final mapping correction; affected focused tests after correction: **62 passed**. Full PostgreSQL-backed Python suite: **849 passed, 1 skipped, 1 existing deprecation warning** on both the initial and final checkpoint runs. Python compileall, JavaScript syntax, Matter `npm run check`, Matter local endpoint validation, active configuration safety grep, and `git diff --check` passed. Docker image build was not run locally because Docker is unavailable in this workspace; hosted CI is pending a commit. No HIL test or live-host deployment was performed.

### Remaining risks and phases

- Migration 025 must be backed up, tested on an installed-database clone, applied deliberately, and verified before any HCM image containing this change is deployed. The live Jetson database has not been modified.
- Matter retry behavior is software-tested with a fake child; real process restart, commissioning persistence, controller behavior, and IPv6/mDNS remain to be validated in a controlled deployment.
- Phase A: extend canonical adapters for SIM/RMC sensor and future module capabilities without changing control authority. Phase B: expand semantically valid Matter mappings and prove stable identity. Phase C: native time service. Phase D: native NWS service and alert cache. Phase E: admin UI refocus. Phase F: dependency-led legacy integration retirement. Docker rollback retention and full HIL acceptance remain separate work.
