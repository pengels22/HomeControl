# HomeControl

HomeControl is the source repository for the HCM (House Control Module) system and its distributed modules.

## Repository layout

- `01_HCM` — Central HCM / Orange Pi 6 application and orchestration
- `02_SIM` — Sensor Interface Module software
- `03_LCM` — Lighting Control Module software
- `04_RCM` — Relay Control Module software
- `05_PNL` — PoE wall-panel software / kiosk agent
- `06_config` — Module-type configuration templates and deployment configuration
- `07_servises` — Shared/system services used by HCM and modules
- `08_database` — PostgreSQL schema, migrations, seed data, and database tooling
- `09_documentation` — Architecture, wiring, networking, HVAC, commissioning, and build documentation
- `10_scripts` — Local simulator, provisioning helpers, and admin tooling
- `11_tests` — Python test coverage for shared services, module behavior, and simulator flows
- `12_IOS` — iOS companion app prototype

## Architecture baseline

HCM is the central controller. It owns device management, PostgreSQL, the rules engine,
authentication, fault management, updates, backups, web UI, Zigbee2MQTT integration,
media control, wall-panel management, and life-safety orchestration.

### HCM control network

- VLAN 60: `192.168.60.0/24`
- HCM/router: `192.168.60.1`
- RCM: `192.168.60.20-29`
- LCM: `192.168.60.30-39`
- SIM: `192.168.60.40-49`
- PNL: `192.168.60.50+`
- Switch port 1: OPI6 NIC 1, `U1,T20`
- Switch port 2: OPI6 NIC 2, `U60`
- Switch ports 3-16: HCM modules, `U60`

Modules self-identify by type on first boot. HCM assigns the next hostname/IP in the
correct pool, the module reboots with its permanent identity, and HCM pushes the base
configuration for that module type.

### Module communication

- Persistent TCP
- TLS authentication
- Length-prefixed JSON
- TCP health + module heartbeat + HCM heartbeat acknowledgement
- Message classes: identify, heartbeat, state, fault, command, command acknowledgement

### Core design rules

- PostgreSQL is authoritative.
- Automation targets logical devices, never physical addresses.
- Output priority:
  1. Maintenance Lock
  2. Life Safety
  3. Local Override
  4. HCM Rules/User Commands
- VLAN 60 has no normal Internet access.
- During updates, HCM temporarily opens egress only for the module being updated.
- HCM provides NTP to VLAN 60.
- Local-first and no-code administration are design goals.

## Current implementation status

This repository now contains runnable first-pass software for HCM, Linux modules,
shared services, deployment scripts, a macOS simulator, and an iOS companion app
prototype. Some production integrations remain intentionally abstracted until
hardware and deployment hosts are connected.

### Local simulator

Run the local simulator on macOS:

```bash
.venv/bin/python 10_scripts/simulate_homecontrol.py
```

Open `http://127.0.0.1:8088` on the Mac running the simulator, or use
`http://100.71.53.54:8088` from the iOS app/device network. The simulator
provides the HCM dashboard, Devices, Service, Settings, and Users tabs. Device
pages expose functional simulated RCM, LCM, SIM, PNL, RMC telemetry, HVAC,
relay, dimmer, lock, naming, and pairing flows without touching physical GPIO,
I2C, CAN, PostgreSQL, or systemd.

### Secure circular pairing

The HCM generates a custom circular optical pairing code for the 3.3-inch local
screen. The code carries an opaque `HC2:...` pairing payload. The iOS app
captures the circular pattern as an image, decodes the fixed HomeControl optical
format, and posts the opaque payload to HCM. HCM verifies/decrypts it using its
own secret and the active pairing record. On success, HCM returns the app session
token. The HCM secret is not stored in the iOS app.

## Module details

### 01_HCM

Central HCM software for the Orange Pi 6. Responsibilities include device
commissioning and management, DHCP and hostname assignment for VLAN 60, NTP,
the rules engine, authentication, fault management, update orchestration,
PostgreSQL integration, web UI, Zigbee2MQTT integration, media control,
wall-panel management, life-safety orchestration, HVAC thermostat and zoning
logic, and the iOS app API.

- NIC 1: VLAN 1 untagged and VLAN 20 tagged
- NIC 2: VLAN 60 at `192.168.60.1`

### 02_SIM

Sensor Interface Module software. Planned responsibilities include SIM
firmware/software, CAN/RMC interface handling, fault reporting, heartbeat logic,
update service integration, and configuration loading.

### 03_LCM

Lighting Control Module software. Pinned hardware additions include:

- 8 hardwired 0-10 V dimming outputs, labeled `10-1` through `10-8`
- 4 high-voltage Shelly dimmer channels, labeled `HV-1` through `HV-4`
- 8 dedicated 24 AWG / 2C pairs through C3
- An I2C multiplexer feeding 8 MCP4725-based 0-10 V modules
- Relay/output behavior as part of the existing LCM design

The simulator UI exposes editable relay and dimmer names. Low-voltage dimmers
use 0-100 sliders and the backend fades to the selected value over 3 seconds.
High-voltage dimmer channels are displayed as 0-100 values without slider-based
control in the current UI.

### 04_RCM

Relay Control Module software. Relay banks are named A1-A8, B1-B8, C1-C8, and
D1-D8. The design uses 5 V opto-isolated relay boards with 2, 4, or 8 channels
as required, controlled from MCP23017 I/O with dry-contact field outputs. Each
relay channel has a configurable fail action.

### 05_PNL

PoE wall-panel software. The pinned platform is an Orange Pi Zero with a 7-inch
touchscreen, PoE, Linux kiosk, Chromium, and a panel agent. HCM provisions each
panel with its hostname, software, token, dashboard URL, and DHCP reservation.

## Configuration status

Configuration schemas are placeholders until finalized for each module type:
HCM, SIM, LCM, RCM, and PNL. Their configuration directories are under
`06_config/`.

## Shared services

Planned service areas under `07_servises/` include:

- Module update service (TCP 6503)
- DHCP and commissioning support
- NTP
- HCM-module communication service
- Authentication support
- Logging and health monitoring

The directory spelling follows the requested repository tree.

## Database

`08_database/` contains the planned PostgreSQL schema, migrations, seed data,
and tooling. PostgreSQL is authoritative for modules, rooms, logical devices,
bindings, faults, users, rules, scenes, wall panels, media, and configuration
history. The exact schema is deferred until implementation.
