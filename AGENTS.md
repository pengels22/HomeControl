# AGENTS.md

## Active watchdog reference (2026-10-10)

Jetson now has a successfully tested HCM-only watchdog. Maintain `10_scripts/hcm-watchdog.py`, `07_servises/systemd/hcm-watchdog.service` and `.timer`, and consult [watchdog deployment record](09_documentation/JETSON_HCM_WATCHDOG_2026-10-10.md) when changing the Docker service lifecycle. The installed watchdog must never restart PostgreSQL or host Heartbeat V3, and should suppress recovery when `hcm.service` is intentionally stopped. Do not claim phone notifications or 3/15-minute rate limiting have been validated.


## Jetson deployment safeguards (2026-10-10)

The live development HCM on Jetson Xavier NX runs inside Docker (Python 3.13), with PostgreSQL 16 on a separate private Docker network and USB-mounted data. Heartbeat V3 remains an independent host Python 3.6 service. Four enabled systemd units recovered after reboot. See [Jetson deployment runbook](09_documentation/JETSON_HCM_DEPLOYMENT_2026-10-10.md) before working on the live host. Do not apply the legacy docker-compose or native-venv HCM service to this host; never commit actual credentials, password files, database or bearer tokens. HCM oneshot startup is not continuous crash recovery. Physical GPIO and production TLS remain unverified.

## Project intent

HomeControl is a local-first, modular house-control system. Preserve the pinned
architecture unless a change is explicitly approved.

## Architectural constraints

- HCM is the central authority.
- PostgreSQL is authoritative for configuration and logical-device mapping.
- User automations and UI logic use logical device names, not hardware addresses.
- RCM, LCM, SIM, and PNL devices communicate with HCM over persistent TLS-protected TCP.
- Do not create direct app-to-module control paths.
- VLAN 20 is the current HCM development/control network; do not migrate running devices yet.
- VLAN 40 is reserved for the future production HCM control network; do not invent a subnet.
- VLAN 60 is permanently reserved for heartbeat and supervisory traffic on TCP 6004.
- VLAN 140 is not applicable to this HCM installation.
- Life-safety behavior must remain separated from convenience automation.
- Maintenance Lockout has higher output priority than Fire/Life Safety.
- Maintenance Lockout applies only to controlled outputs; DI and AI inputs must keep sensing/reporting.
- Dedicated HCM safety relays/inputs are separately classified and are not normal automation outputs.
- Do not silently change hardware pinouts, network ranges, relay numbering, fail states,
  or HVAC timing.

## Pinned network decisions

- Current development/control VLAN: 20
- Future production/control VLAN: 40, subnet not yet approved
- Heartbeat/supervisory VLAN: 60
- Conflict Manager heartbeat address: 192.168.60.2 on eth0.60
- Heartbeat TCP port: 6004
- Unified Heartbeat V3 in `00_Heartbeat/` is the standard implementation
- Device IDs are normalized MAC addresses from the designated physical interface:
  lowercase, colons removed, exactly 12 hexadecimal characters

## Pinned relay naming

Relay banks are `A`, `B`, `C`, and `D`, each with channels `1-8`.
Examples: `A1`, `B2`, `C3`, `D4`.

LCM 0-10 V dimmer outputs are labeled `10-1` through `10-8`.

## HVAC controls

HCM is the thermostat. Global modes are HEAT, COOL, FAN, and OFF.

- Global setpoint and mode
- Only occupied actuated rooms drive active zoning demand
- Non-actuated rooms remain available as airflow paths and participate in the house temperature model
- Damper command -> 500 ms -> fan -> 500 ms -> heat/cool call
- COOL minimum run: 2 minutes
- HEAT minimum run: 1 minute
- Y restart lockout: 5 minutes
- W restart lockout: 5 minutes
- Fan post-run after heat/cool: 60 seconds
- FAN mode runs until changed by user or automation
- OFF opens all HVAC call relays
- Failed room sensor causes that room damper to default open

## Safety

Do not weaken fire handling, maintenance lock behavior, fail actions, or output-priority
logic without explicit approval.
