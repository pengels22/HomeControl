# Pinned Architecture Baseline

## Core

HCM is the central controller.

Module types:
- RCM — Relay Control Module
- LCM — Lighting Control Module
- SIM — Sensor Interface Module
- RMC — Room Monitoring Cluster
- PNL — PoE wall panel

## Networking

- Dedicated HCM VLAN: 60
- Network: 192.168.60.0/24
- HCM: 192.168.60.1
- RCM: .20-.29
- LCM: .30-.39
- SIM: .40-.49
- PNL: .50+

Switch:
- Port 1: U1,T20 -> OPI6 NIC 1
- Port 2: U60 -> OPI6 NIC 2
- Ports 3-16: U60 -> modules

VLAN 60 receives no normal Internet access.
HCM provides local NTP.
During staged updates HCM temporarily opens WAN access only for the module being updated.

## Commissioning

New modules boot with a generic hostname matching module type.
HCM automatically:
1. identifies module type
2. assigns next number and address from the correct pool
3. records the permanent assignment
4. causes the module to reboot with its permanent identity
5. verifies its return
6. pushes the base configuration for that module type

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

## Output priority

1. Maintenance Lock
2. Life Safety
3. Local Override
4. HCM Rules/User Commands

## LCM analog dimming

- 8 hardwired 0-10 V outputs
- `10-1` through `10-8`
- 8 x 24 AWG / 2C pairs through C3
- I2C multiplexer
- 8 MCP4725-based 0-10 V modules
- hardwired directly to corresponding LED drivers

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
- turns on all available, non-maintenance-locked lights
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
- UniFi Protect remains responsible for camera UI
