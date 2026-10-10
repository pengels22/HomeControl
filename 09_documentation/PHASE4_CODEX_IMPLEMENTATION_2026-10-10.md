# Phase 4 — HCM Application Foundation: Codex Implementation Contract

**Status:** planning / implementation instructions, 2026-10-10. **Not a claim that Phase 4 features are deployed.** Read the repository documentation and live deployment runbooks before any code change.

## Mandatory documentation-first workflow

1. Read `AGENTS.md` and the complete root `README.md`.
2. Inventory and read the relevant documents under `09_documentation/`, especially `JETSON_HCM_DEPLOYMENT_2026-10-10.md`, `JETSON_2026-10-10_STATUS.md`, and `JETSON_HCM_WATCHDOG_2026-10-10.md`. Read `00_Heartbeat/README.md` and the module/configuration/database docs for anything you touch. Inspect `06_config/`, `08_database/`, `01_HCM/`, `07_servises/`, `10_scripts/` and tests as necessary. **Do not assume an older paragraph supersedes a newer dated operational record.**
3. Compare the *current implementation* to the stated architecture and the live-host snapshot. Report inconsistencies, ambiguities, dependencies and proposed changes **before editing**. Prefer narrow additive changes over broad refactoring. Ask for approval before modifying pinned decisions, existing APIs, database schemas, network/security settings, systemd, Docker networking, Heartbeat V3, hardware mappings or safety behavior.
4. Establish a clean Git working tree; preserve unrelated or uncommitted work. Work in reviewable commits/PRs with tests and documentation. Do not push changes or deploy/restart live services without explicit operator approval.

## Verified live baseline — preserve it

- Jetson Xavier NX: `eth0=192.168.20.27/24` via DHCP reservation (metric 100), `wlan0=192.168.20.25/24` via DHCP reservation (metric 300 **saved** in NetworkManager; observed runtime remained 600 until reconnect). Ethernet is preferred. The live Netplan Ethernet configuration is `networkd`; Wi-Fi `Lab 42` is NetworkManager-controlled. Do not revert to old static `192.168.1.63`.
- Conflict Manager: USB Ethernet `enx6c6e07545f03=192.168.20.26/24` (metric 100); `wlan0=192.168.20.24/24` (metric 300 configured) via DHCP reservations. Ethernet preferred. Preserve Conflict device identity `3c53bbf7adb2` derived from `wlan0`; do not substitute the USB adapter MAC.
- Both devices run on **VLAN 20** for the verified development deployment. VLAN 40 control and VLAN 60 supervisory/heartbeat are **future, not deployed**; never migrate them automatically. Do not reinterpret legacy `192.168.60.2` as the live Conflict endpoint.
- Unified Heartbeat V3 is independent of Docker/HCM. Jetson `hcm-heartbeat.service` host Python 3.6, Jetson identity `eth0`, advertised `192.168.20.27`, Conflict destination `192.168.20.26`, TCP 6004. Conflict listener `192.168.20.26:6004`, identity `wlan0`. Live `/status` showed healthy/operational Jetson peer, last seen ~3 s. Do not change heartbeat protocol/service or life-safety supervision while implementing Phase 4.
- HCM: Docker image `homecontrol-hcm:phase3` (Python 3.13), container `hcm-test`, dashboard/API published `192.168.20.27:8080`. PostgreSQL 16 `hcm-postgres` on private Docker network with persistent USB-mounted storage under `/srv/hcm-data/postgres`. Preserve bridge isolation, database credentials and systemd startup dependencies.
- Live `hcm.service` requires Docker and `hcm-postgres.service`; it **no longer requires** `hcm-routing.service`. The old `ExecStartPost=/usr/local/sbin/hcm-update-routing` drop-in is disabled, `hcm-routing.service` is disabled, and special policy rule 1100 (Docker `172.19.0.2` → Mac `192.168.1.241`) is removed. **Do not restore** any of them. Wi-Fi-specific source policy rule 1000 / table 200 remains for Wi-Fi-originated traffic; do not remove or repurpose without approval.
- Reboot and subsequent checks verified Ethernet routes to Conflict, `hcm`, `hcm-postgres`, `hcm-heartbeat`, `hcm-watchdog.timer` active; `hcm-test` running, dashboard GET `/` returned HTTP 200. Watchdog's controlled-kill recovery was previously tested, but its suppression/notifications remain untested/deferred. Do not claim HTTP 200 proves full functional or safety validation.
- The root `docker-compose.yml` and `07_servises/systemd/homecontrol-hcm.service` are **legacy/alternative examples**, not the installed Jetson deployment. Do not replace live Docker/systemd with them. Never commit credentials, tokens, the live DB, private keys or service environment files.

## Phase 4 objective and bounded scope

Build an incremental **device/module registry and management foundation** on the existing HCM application, reusing existing code, naming, models, routes, UI, migrations and test conventions. PostgreSQL must remain the system of record for authoritative device/module metadata. Keep *logical device identity and bindings* separate from hostnames, MAC IDs, IP addresses, and physical channels.

Proposed deliverables, only after examining existing implementation:
1. Inventory existing device registry/commissioning, module identification, logical-device mapping, database schema, API and UI; produce a gap analysis and minimal implementation plan. Do **not** recreate implemented features.
2. Add only missing persistence/migrations for module/device identity, type/capabilities, state, desired configuration, linkage to logical devices and auditable changes. Use additive, reversible migrations; never reinitialize or overwrite the existing DB.
3. Add/extend backend registration, query, validation, update, status and logical-binding APIs consistent with existing authentication and permissions. Treat MAC-based identity as a claimed identifier, not network authentication. Idempotent registration and clear offline/stale handling.
4. Extend existing dashboard's Devices view for discovery/registered modules, logical names, capability summaries and health. Prefer existing components and simulator fixtures. Keep irreversible/output control out of scope until explicit approval.
5. Extend tests for migration safety, idempotency, API authorization, identity collisions, stale/offline handling, and simulator flows. Document exact local test commands and operator-approved deployment/rollback procedures.

### Hard boundaries

- **No surprise changes** to networking, VLANs, routing metrics, DHCP reservations, firewall, SSH/Tailscale, Docker networking, PostgreSQL instance/storage, watchdog, host systemd or heartbeat.
- **No hardware actuation** or changes to SIM/LCM/RCM/PNL pinouts, MCP mappings, relay bank/channel numbering, dimming ranges, HVAC timing or life-safety responses. Preserve output precedence and maintenance lockout.
- Do not migrate VLAN 20 to 40 or 60, do not re-enable route 1100, do not change Conflict identity from `wlan0`, and do not move HCM off `192.168.20.27:8080`.
- Existing actual hardware and life-safety paths are not commissioned by this phase. Notifications and companion app integration are deferred.
- If documentation conflicts or is ambiguous, cite paths/sections, identify the newest verified record, **stop and ask** rather than selecting a historic baseline or silently "fixing" it.

## Required Codex delivery format

Before implementation return: (a) documents and code inspected with paths, (b) verified current behavior vs proposed gaps, (c) exact files/migrations/APIs/tests to touch, (d) risks/rollback, (e) approval questions. After approval implement in small reviewable stages, run tests, provide diff/test summary and update the applicable docs. Deployment to the live Jetson requires a separate explicit go-ahead.
