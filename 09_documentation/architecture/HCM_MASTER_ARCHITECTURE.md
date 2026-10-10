# HCM Master Architecture

## Deployed development implementation (2026-10-10)

The Jetson Xavier NX now runs the HCM FastAPI server in a Python 3.13 container connected to PostgreSQL 16 via a private Docker bridge. The dashboard/authentication, data mount, networking and automatic boot of HCM/PostgreSQL/routing/host Heartbeat V3 have been operator validated. See [verified runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md). This is a **development deployment** and does not establish readiness for hardware safety, production certificates, notifications, dynamic access rules, crash recovery or flash-storage durability. Future-state architectural requirements below remain goals rather than statements about live installation.


This document reconciles the current repository with the newer HomeControl/HCM
architecture brief. It is descriptive, not a silent migration plan. Items marked
planned or unresolved must be confirmed before implementation changes.

## Authority Model

HomeControl is a local-first distributed house-control system. HCM is the central
authority for application logic, user authentication, configuration,
commissioning, logical-device mapping, automation, HVAC control, and normal user
interfaces.

PostgreSQL is the intended authoritative store for:

- Linux module registration, normalized MAC-derived device IDs, hostnames, IP
  assignments, software/config version, online state, and last state.
- Rooms and room HVAC state.
- Logical devices and bindings from logical names to module channels.
- Output intents and priority arbitration.
- Faults, safety events, users, sessions, pairing keys, rules, scenes,
  configuration history, firmware packages, and RMC firmware update history.

The current schema is implemented in `08_database/schema.sql`. HCM code uses it
through `asyncpg` in `01_HCM/db.py`. Some features are schema-backed but still
first-pass implementations.

## Processors And Modules

### HCM

Current HCM software lives in `01_HCM/`.

Implemented:

- FastAPI application with REST endpoints and static web UI mounting.
- Module registry listener on TCP 6501.
- Password login, session tokens, pairing keys, and development session flow.
- PostgreSQL-backed HVAC mode/setpoint/room persistence.
- HVAC state machine with pinned timing constants.
- Logical-device command path through PostgreSQL bindings.
- Output-intent priority for life safety, local override, user, and rules.
- Fire event API path that logs a safety event, forces HVAC off, sends a
  notification, and commands non-maintenance-locked lights on. This matches the
  approved maintenance lockout priority but still needs final emergency-output
  designation.
- RMC firmware update orchestration entry point.

Unverified or incomplete:

- Production GPIO fire input monitoring.
- Production WebAuthn/passkey verification.
- Production APNs, Apple Watch, and critical notification delivery.
- Production DHCP, NTP, firewall, TLS certificate provisioning, and deployment
  automation.
- Production web UI completeness.

### Linux Modules

The Linux module base class is `07_servises/common/agent.py`. It implements:

- Persistent local module identity in a JSON file.
- HCM connection over length-prefixed JSON frames.
- `identify`, `assignment`, `config`, `heartbeat`, `heartbeat_ack`, `command`,
  and `command_ack` message flow.
- Optional TLS client connection.
- Local status-only web UI that authenticates through HCM and does not expose
  direct control commands.

This module heartbeat is separate from Unified Heartbeat V3 and is an explicit
architecture conflict until the roles are reconciled.

### SIM

`02_SIM/main.py` implements a Sensor Interface Module agent with:

- SocketCAN configuration/state model.
- RMC CAN frame decoding.
- RMC telemetry, heartbeat, fault, and fault-clear state capture.
- Hexa board manifest for AIO, DIO, USB, CAN, and 12 V switching.
- Simulated controls for Hexa DIO and 12 V switching.
- RMC firmware update staging and Classical CAN transfer simulation.

Real sensor and CAN deployment remain partly unverified. `06_config/02_SIM/`
contains SocketCAN setup files and pinout documentation.

### LCM

`03_LCM/main.py` implements a Lighting Control Module agent with:

- Logical relay outputs.
- Four high-voltage dimmer channel labels, `HV-1` through `HV-4`.
- Eight low-voltage 0-10 V outputs, `10-1` through `10-8`.
- TCA/PCA9548A mux plus MCP4725 DAC model for low-voltage dimmers.
- Simulated or real I2C selection through IO mode.

The macOS simulator implements the user-facing low-voltage dimmer fade behavior.
The module driver sets DAC output directly when commanded; production fade origin
and timing should be reconciled before hardware use.

### RCM

`04_RCM/main.py` implements a Relay Control Module agent with:

- Relay channels `A1-A8`, `B1-B8`, `C1-C8`, and `D1-D8`.
- Pinout loading from `06_config/04_RCM/Pinout.md`.
- Required-channel validation.
- Simulated relay state.
- Command handling for `set_relay` and `all_off`.

`fail_actions` exists in config plumbing but is not enforced by hardware driver
logic yet.

### PNL

`05_PNL/main.py` implements a minimal PoE panel agent with room and dashboard URL
state. The panel software is first-pass and the final kiosk UI is planned.

### RMC

RMC is a microcontroller CAN room node, not a Linux service. The repo includes:

- `06_config/06_RMC/RMC.ino` firmware for an Arduino Nano-class RMC.
- `06_config/06_RMC/rmc.yaml` and `Pinout.md`.
- CAN IDs for telemetry, heartbeat, fault, fault-clear, and firmware update.
- ENS160/AHT21, BH1750, RCWL-0516, and MCP2515/TJA1050 sensor stack.

RMC firmware update transport is HCM -> SIM -> CAN -> RMC. There must not be a
direct HCM-to-RMC firmware/control path.

### Conflict Manager

The conflict manager is an independent supervisory processor. The current V3
heartbeat daemon in `00_Heartbeat/` can run in `conflict` role and maintain a
persistent SQLite peer registry and event history. This service must remain
independent of the primary HCM application and PostgreSQL.

The current repository does not integrate Conflict Manager state into HCM's
PostgreSQL module registry or UI as an authoritative control path.

## Networks

Approved network decisions:

- VLAN 20 is the current HCM development/control network. Existing running
  devices must not be migrated yet.
- VLAN 40 will become the dedicated production HCM control network. Do not
  invent or document a VLAN 40 subnet or pools without approval.
- VLAN 60 is permanently reserved for heartbeat/supervisory traffic between
  modules/devices and the Conflict Manager.
- VLAN 140 is not applicable to this HCM installation.
- Conflict Manager heartbeat address is `192.168.60.2` on `eth0.60`.
- Heartbeat communications use TCP 6004 and Unified Heartbeat V3 in
  `00_Heartbeat/`.

The HCM registry now uses `06_config/01_HCM/hcm.yaml` for control-network
assignment. The active template profile is VLAN 20 development/control, with
future VLAN 40 present but disabled until an approved subnet and pools are
entered. VLAN 60 is explicitly rejected as a module-control assignment network.

The current development/control baseline uses VLAN 20 addresses, including
Conflict at `192.168.20.26` and Jetson/HCM at `192.168.20.27`.

This must be migrated deliberately: module control/config traffic moves from
current VLAN 20 to future VLAN 40 only after the VLAN 40 subnet and pools are
approved. Existing device records are not automatically moved between networks.

## Device Identity

The authoritative device ID is the MAC address of a designated physical network
interface, normalized by converting to lowercase and removing colons. Example:
`48:b0:2d:87:db:16` becomes `48b02d87db16`.

This ID replaces separately generated module UUIDs. It is exactly 12
hexadecimal characters and must not be stored or validated as a standard 128-bit
UUID. Human-readable hostnames and logical device names remain separate.

## Communication Paths

Current implemented paths:

- iOS/app/browser -> HCM API only.
- HCM -> Linux modules over persistent TCP 6501, length-prefixed JSON, optional
  TLS.
- Linux modules -> HCM through the same persistent TCP session for state,
  faults, and module heartbeats.
- HCM -> SIM -> CAN -> RMC for RMC firmware updates.
- Unified Heartbeat V3 devices -> Conflict Manager over HTTP on TCP 6004.
- Local heartbeat status/fault updates -> Unix socket
  `/run/hcm-heartbeat/control.sock`.

Prohibited or not implemented:

- Direct app-to-module control paths.
- Direct HCM-to-RMC control path.
- Using unauthenticated heartbeat messages as safety authorization.

## Interfaces

Current user/admin interfaces:

- HCM FastAPI API under `/api/v1`.
- HCM web UI scaffold under `01_HCM/www`.
- macOS simulator on port 8088.
- Module status-only web UIs on default ports 8092-8095.
- iOS companion app prototype under `12_IOS/Home Control`.

The UI should remain logical-device-oriented. Hardware channels should be
binding/configuration details, not everyday automation targets.

## Local-First Constraint

Core control, safety, supervision, and HVAC behavior must not depend on cloud
connectivity. Current production-target services are local Python/systemd,
PostgreSQL, TCP, CAN, and local web/API components. External integrations such
as push notifications or future remote access are convenience layers, not core
authority.
