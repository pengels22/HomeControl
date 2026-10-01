# AGENTS.md

## Project intent

HomeControl is a local-first, modular house-control system. Preserve the pinned
architecture unless a change is explicitly approved.

## Architectural constraints

- HCM is the central authority.
- PostgreSQL is authoritative for configuration and logical-device mapping.
- User automations and UI logic use logical device names, not hardware addresses.
- RCM, LCM, SIM, and PNL devices communicate with HCM over persistent TLS-protected TCP.
- Do not create direct app-to-module control paths.
- VLAN 60 modules must not require normal Internet access.
- Life-safety behavior must remain separated from convenience automation.
- Maintenance Lock has higher output priority than Life Safety.
- Do not silently change hardware pinouts, network ranges, relay numbering, fail states,
  or HVAC timing.

## Pinned network ranges

- HCM: 192.168.60.1
- RCM: 192.168.60.20-29
- LCM: 192.168.60.30-39
- SIM: 192.168.60.40-49
- PNL: 192.168.60.50+

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
