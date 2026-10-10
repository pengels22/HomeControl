# Pinned Architecture Baseline

## Runtime deployment clarification (2026-10-10)

The approved future-state network and safety requirements below remain unchanged. The current Jetson development HCM application runs in Docker on VLAN 20, its PostgreSQL database uses a separate private Docker bridge and mounted USB, and host Heartbeat V3 remains independent on the existing TCP 6004 network. VLAN 40 control and VLAN 60 heartbeat migration have **not** been performed. Read [Jetson runbook](JETSON_HCM_DEPLOYMENT_2026-10-10.md). Successful UI/database commissioning does not validate production safety I/O or hardwired fire actions.


## Core

HCM is the central controller.

Module types:
- RCM — Relay Control Module
- LCM — Lighting Control Module
- SIM — Sensor Interface Module
- RMC — Room Monitoring Cluster
- PNL — PoE wall panel

## Networking

- VLAN 20: current HCM development/control network.
- VLAN 40: future dedicated production HCM control network. Subnet and module
  pools are not approved yet.
- VLAN 60: heartbeat/supervisory network only.
- VLAN 140: not applicable to this HCM installation.
- Conflict Manager heartbeat address: 192.168.60.2 on eth0.60.
- Heartbeat TCP port: 6004.
- Unified Heartbeat V3 in `00_Heartbeat/` is the standard heartbeat
  implementation.

Do not migrate existing running devices from VLAN 20 yet. Do not invent a VLAN
40 subnet. VLAN 60 must not carry normal app, module-control, update, web UI, or
database traffic.

HCM provides local NTP on the approved control network. During staged updates,
HCM temporarily opens WAN access only for the module being updated.

## Commissioning

New modules boot with a generic hostname matching module type.
HCM automatically:
1. identifies module type
2. reads the normalized MAC-derived device ID from the designated physical interface
3. assigns next hostname and approved control-network address
4. records the permanent assignment
5. causes the module to reboot with its permanent identity
6. verifies its return
7. pushes the base configuration for that module type

The normalized device ID is the physical interface MAC address converted to
lowercase with colons removed, for example `48:b0:2d:87:db:16` becomes
`48b02d87db16`. It replaces generated module UUIDs and is not a 128-bit UUID.

## Communications

- persistent TCP
- TLS
- length-prefixed JSON
- TCP health
- module heartbeat
- HCM heartbeat acknowledgement

Messages:
- identify
- heartbeat
- state
- fault
- command
- command acknowledgement

## Authentication and pairing

HCM remains the central authentication authority.

- Usernames and password hashes live on HCM, backed by PostgreSQL.
- Passwords are not stored in plain text.
- Module web UIs require HCM-issued bearer tokens.
- The iOS app talks to HCM only; it does not create direct app-to-module control paths.
- HCM local-screen pairing uses a standards-compliant QR URL inside the circular pairing UI.
- The QR URL carries an opaque `HC2:...` signed/encrypted pairing payload.
- The iOS app scans the QR and extracts the opaque payload, but does not hold the HCM pairing secret.
- HCM verifies/decrypts the opaque pairing payload against its active pairing record.
- A valid pairing payload can be exchanged for an app session token.

## Output priority

1. Maintenance Lockout
2. Fire/Life Safety
3. Local Override
4. HCM Rules/User Commands

Maintenance lockout is the highest-priority output inhibit. While active, no
controlled output may energize, including during fire response. Fire detection,
fault reporting, event logging, and communication must continue where possible.

## LCM analog dimming

- 8 hardwired 0-10 V outputs
- `10-1` through `10-8`
- backend fade time target: 3 seconds for slider-originated low-voltage dimming commands
- 8 x 24 AWG / 2C pairs through C3
- I2C multiplexer
- 8 MCP4725-based 0-10 V modules
- hardwired directly to corresponding LED drivers

## LCM high-voltage dimming

- 4 high-voltage dimmer channels
- channels are labeled `HV-1` through `HV-4`
- hardware target is two Shelly Dimmer Pro 2-channel modules
- UI displays values as 0-100 percent

## RCM relay layout

32 outputs:
- A1-A8
- B1-B8
- C1-C8
- D1-D8

Each 8-channel bank uses a 10-position pluggable terminal connector.
Common field feed is grouped four channels at a time.

## HVAC

HCM replaces the thermostat.

Global:
- modes: HEAT / COOL / FAN / OFF
- one global setpoint
- 1 F control deadband

Sequence:
1. command required dampers
2. wait 500 ms
3. fan ON
4. wait 500 ms
5. heat or cool ON

Run protection:
- cooling minimum run: 2 minutes
- heating minimum run: 1 minute
- cooling restart lockout: 5 minutes
- heating restart lockout: 5 minutes
- fan post-run: 60 seconds

Occupancy/zoning:
- actuated dampers open when the room requires conditioning
- occupancy changes wait until the active call ends before zoning is recalculated
- failed room sensor -> damper defaults open
- fan mode remains ON until user/automation changes mode
- OFF -> all HVAC call relays open
- selected non-actuated rooms preserve an airflow path to prevent deadheading

## Life safety

Dedicated wired fire relay input to HCM.
HIGH = normal.
LOW = fire active.

Fire:
- enters life-safety mode
- when maintenance lockout is inactive, turns on designated emergency lighting outputs
- shuts HVAC down
- sends critical iOS app alert
- issues fire TTS warning
- logs/latches the event

## Companion app

Initial platform: iOS only.
Initial connectivity: local only.
Future remote access may use Tailscale.

- biometric authentication
- challenge/response passkey model
- normal push notifications
- critical notifications
- Apple Watch support
- global HVAC controls
- room light toggles
- double-tap light for dimmer
- media controls
- ADMIN and READONLY roles
- app talks only to HCM
- circular pairing capture posts opaque payloads to HCM for verification
- UniFi Protect remains responsible for camera UI
