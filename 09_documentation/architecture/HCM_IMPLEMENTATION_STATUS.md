# HCM Implementation Status

## Later operator validation: application watchdog (2026-10-10)

Since the initial implementation matrix and reboot addendum, a timer-driven HCM health monitor has been installed and tested with `docker kill hcm-test`. Three failed checks triggered a systemd HCM-only restart and routing restoration; PostgreSQL and independent Heartbeat V3 services remained active. See [watchdog verification](../JETSON_HCM_WATCHDOG_2026-10-10.md). This does not prove PostgreSQL crash recovery, the 3/15-minute restart cap, alert delivery, safety I/O, or backups.


## 2026-10-10 live deployment addendum

This older matrix primarily describes repository-level verification. Subsequent operator testing confirmed **real** PostgreSQL schema and password/session login, the HCM FastAPI dashboard in Docker on Jetson Xavier NX, and successful automatic boot of the HCM, routing, PostgreSQL and independent Heartbeat V3 services after a full Jetson reboot. The USB data volume remained mounted and the dashboard loaded. Authentication SQL interval binding and web login visibility were corrected in the committed source. See [deployment runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md) and [dated status](../JETSON_2026-10-10_STATUS.md). The statements below describing database connectivity, Jetson runtime, or systemd as unverified are superseded **for this specific development deployment only**. Physical GPIO, real safety paths, TLS, continuous crash recovery and backup/restore remain unverified.


This status reflects repository review, not hardware validation.

## Status Key

- Complete: implemented and covered well enough for its current scope.
- Implemented/tested: implemented with focused automated tests, still may not be
  production complete.
- Implemented/unverified: code exists but hardware or deployment validation is
  missing.
- Partial: meaningful scaffolding exists, major behavior remains.
- Simulated: works in simulator/dev mode only.
- Planned: described but not implemented.
- Conflict: implemented or documented behavior contradicts another requirement.

## Repository And Tooling

| Area | Status | Notes |
|---|---|---|
| Numbered repository layout | Complete | Expected folders exist, including `07_servises`. |
| Python packaging | Implemented/tested | `pyproject.toml`, requirements, tests present. |
| systemd unit templates | Partial | HCM/module/update units exist; live deployment unverified. |
| Install scripts | Partial | HCM/modules/SIM CAN scripts exist; not validated on target hardware here. |
| macOS simulator | Implemented/tested | Exercises HCM/HVAC/RCM/LCM/SIM/PNL/RMC flows without hardware. |

## HCM Core

| Area | Status | Notes |
|---|---|---|
| FastAPI app | Implemented/tested | API routes and static UI mount exist. |
| PostgreSQL connection | Implemented/unverified | Uses asyncpg; tests often mock DB. |
| Schema | Implemented | Covers modules, devices, HVAC, faults, users, pairing, rules, scenes, firmware. |
| Authentication | Partial | Password/session flows implemented; WebAuthn production adapter planned. |
| Pairing keys | Implemented/tested | Hash-only storage and one-time verification tested. |
| Circular/QR pairing | Implemented/tested | Simulator and iOS prototype support secure `HC2` payloads. |
| Rules engine | Partial | Skeleton exists; final rules schema/executor planned. |
| Notifications | Partial | Abstraction/logging exists; production APNs/critical alerts planned. |
| Firmware update orchestration | Partial | RMC update route and SIM simulation exist. |
| HCM web UI | Partial | Scaffold exists; production UX incomplete. |

## Module Communication

| Area | Status | Notes |
|---|---|---|
| Length-prefixed JSON protocol | Implemented/tested | `07_servises/common/protocol.py`. |
| Persistent module TCP | Implemented/tested | HCM registry accepts identify/heartbeat/state/fault/command_ack. |
| Module identity persistence | Implemented | JSON identity file generated/stored locally. |
| Automatic hostname/IP assignment | Implemented/tested | Uses configurable control-network profiles from `06_config/01_HCM/hcm.yaml`; active template is VLAN 20. |
| TLS support | Partial | Optional TLS contexts exist; cert provisioning/enforcement unverified. |
| Module local web UI | Implemented/tested | Status-only; HCM auth proxy. |
| Unified Heartbeat V3 integration | Implemented/tested | Module agent reports app status, HCM TCP status, faults, and watchdog pulses to the local V3 daemon socket when present. |

## Unified Heartbeat V3

| Area | Status | Notes |
|---|---|---|
| Python 3.6 daemon | Implemented | Standard library only. |
| Device heartbeat POST | Implemented | Full snapshot sent every interval. |
| Conflict full reply | Implemented | Reply includes full health/status plus echo fields. |
| Local health/status endpoints | Implemented | `/health` and `/status`. |
| Local fault/status/watchdog API | Implemented | Unix socket and CLI. |
| Fault/module persistence | Implemented | State file persists faults/modules. |
| Peer registry persistence | Implemented/tested | Conflict role stores device registry in SQLite and marks peers offline on daemon restart until fresh heartbeat arrives. |
| Event audit history | Implemented/tested | SQLite `heartbeat_events` records registration, heartbeat, offline, online, and duplicate-ID events. |
| Cryptographic auth | Planned/not required yet | Current design is unauthenticated and network-restricted. |

## RCM

| Area | Status | Notes |
|---|---|---|
| 32 relay names | Implemented/tested | `A1-D8` preserved. |
| Pinout parser/validation | Implemented/tested | Requires all relay channels. |
| Relay command simulation | Implemented/tested | DigitalBank state only. |
| MCP23017 hardware driver | Planned | No real GPIO expander driver active. |
| Fail actions | Partial | Config field exists; behavior not enforced. |
| Local override hardware | Planned | Pinout docs mention overrides; driver behavior absent. |

## LCM

| Area | Status | Notes |
|---|---|---|
| Relay channels | Implemented/tested | A/B relay mappings. |
| 0-10 V output labels | Implemented/tested | `10-1` through `10-8`. |
| I2C mux/DAC model | Implemented/tested | Writes modeled; real bus optional. |
| High-voltage dimmer labels | Implemented/tested | `HV-1` through `HV-4`. |
| Simulator dimmer fades | Implemented/tested | 3-second default in simulator path. |
| Production fade ownership | Partial | Module direct command sets value immediately. |
| Shelly integration | Planned | Labels/status exist; production control absent. |
| Health to V3 heartbeat | Implemented/tested | Shared module agent writes status/fault/watchdog events to the V3 Unix socket. |

## SIM And RMC

| Area | Status | Notes |
|---|---|---|
| SIM CAN interface model | Implemented/tested | SocketCAN setup plans and snapshots. |
| Hexa board manifest | Implemented/tested | AIO/DIO/USB/CAN/12 V switching simulated. |
| RMC telemetry decoding | Implemented/tested | Matches firmware layout tests. |
| RMC fault decoding | Implemented/tested | Sensor fault names decoded. |
| RMC firmware package validation | Implemented/tested | SHA/CRC/package checks. |
| SIM-to-RMC update simulation | Implemented/tested | Stages, frames, completes simulated update. |
| Real SocketCAN deployment | Implemented/unverified | Scripts exist; hardware not validated here. |
| RMC bootloader | Planned | Firmware notes require protected bootloader, not included here. |
| Sensor stale/disconnected taxonomy | Partial | Faults decoded; full stale/offline policy incomplete. |

## PNL And iOS

| Area | Status | Notes |
|---|---|---|
| PNL agent | Partial | Room/dashboard state only. |
| PNL kiosk UI | Planned | Final UI not implemented. |
| iOS app prototype | Partial | Pairing, scanner views, client, web view present. |
| Apple Watch | Planned | No watch app found. |
| Remote access | Planned | Future Tailscale mentioned; no implementation. |

## HVAC

| Area | Status | Notes |
|---|---|---|
| Modes | Implemented/tested | HEAT/COOL/FAN/OFF. |
| Setpoint/deadband | Implemented/tested | 1 F deadband. |
| Damper/fan/call sequence | Implemented/tested | 500 ms delays in production constants. |
| Minimum run and restart lockout | Implemented/tested | Cooling/heating protections. |
| Fan post-run | Implemented/tested | 60 seconds. |
| Failed sensor damper fail-open | Implemented/tested | Actuated damper opens. |
| Occupancy-aware demand | Implemented/tested | Occupied actuated rooms plus non-actuated rooms. |
| Hardwired fire shutdown | Planned | Software `force_off()` exists only. |

## Safety

| Area | Status | Notes |
|---|---|---|
| Fire API/software path | Implemented/tested | Logs, HVAC off, critical notification, light sweep. |
| Fire GPIO input | Planned/conflict | Pinout exists; polarity conflict unresolved. |
| Maintenance lock block | Implemented/tested | Blocks logical-device commands. |
| Maintenance lockout priority | Implemented/tested | Shared arbiter exposes requested/effective state and inhibits energize commands across HCM, RCM, LCM, SIM, and simulator paths. |
| Input/output classification | Implemented/tested | SIM DI/AI inputs are not lockout-controlled outputs; DIO outputs and 12 V switching remain arbitrated. |
| HCM safety relays | Implemented/tested | Simulated door-request and auxiliary safety relays are ADMIN-controlled and documented as lockout-exempt; real GPIO remains disabled. |
| Global config loader | Implemented/tested | Loads validated flat defaults from numbered config directories with file provenance. |
| Fire input abstraction | Implemented/tested | Simulated debounced input helper; real GPIO remains intentionally disabled. |
| Phase 3 safety arbitration | Implemented/tested | See `HCM_PHASE3_SAFETY_ARBITRATION.md`; hardware validation remains outstanding. |
| Safety event persistence | Partial | Events inserted; latching/recovery policy incomplete. |
| Independent safety processor/path | Planned | Conflict Manager is heartbeat supervisor, not certified safety path. |

## Networking And Infrastructure

| Area | Status | Notes |
|---|---|---|
| VLAN 20 development/control | Approved/current | Templates point to current development HCM address; no live migration performed. |
| VLAN 40 production/control | Planned/blocked | Dedicated production control network approved, but subnet/pools are not approved. |
| VLAN 60 heartbeat network | Approved/partial | Conflict Manager target address is `192.168.60.2`; Heartbeat V3 is standard; code/config migration still staged. |
| Legacy VLAN 60 module-control assumptions | Implemented/tested | Registry rejects VLAN 60 control profiles and no longer allocates module-control addresses from hardcoded `.60` pools. |
| VLAN 140 | Not applicable | Explicitly out of scope for this HCM installation. |
| DHCP reservation writer | Planned | Assignment model exists; no production writer. |
| NTP service | Planned | Config says local NTP; no implementation found. |
| Firewall update hook | Partial | Dry-run shell hook only. |
| Internet isolation | Planned/deployment | Documented; not enforced by repo code. |

## Test Coverage Summary

Automated tests cover API basics, auth/password/pairing, HVAC behavior, IO mode,
LCM mapping/DAC model, module web UI, pairing glyphs, pinmap parsing, output
priority, registry assignment/TLS guard/heartbeat ack, RMC firmware, SIM CAN and
RMC telemetry, safety fire path, and simulator workflows.

Tests do not validate real hardware, real PostgreSQL migrations in deployment,
systemd behavior on target hosts, network routing, firewall/NTP/DHCP, production
TLS, production WebAuthn, production notifications, or physical safety behavior.
