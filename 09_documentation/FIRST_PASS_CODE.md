# First-pass code status

This repository now contains runnable scaffolding rather than documentation-only placeholders.

Implemented in this pass:
- persistent length-prefixed JSON TCP protocol
- generic module agent with identity persistence and heartbeats
- HCM module registry / automatic IP+hostname assignment model
- PostgreSQL schema for modules, rooms, logical devices, bindings, faults, users, rules, scenes, config history, safety events
- RCM 32-channel logical relay adapter
- LCM 32 relays + 8 logical 0-10 V outputs
- SIM/RMC telemetry integration point
- PNL agent and minimal development web page
- HCM REST API
- HVAC state machine using pinned timings and global mode/setpoint
- life-safety fire controller path
- update service skeleton on TCP 6503
- systemd unit templates
- basic tests

Not production-complete yet:
- real MCP23017, PCA/TCA9548A, MCP4725, GPIO, CAN, and relay hardware drivers
- actual DHCP reservation writer/reloader
- actual local NTP daemon setup
- actual firewall/Zyxel update-window automation
- TLS certificate provisioning and enforcement
- full passkey/WebAuthn verification
- APNs push and Apple Watch app
- final rules schema/executor
- final PNL UI
- OTA/app package deployment logic
- production life-safety GPIO supervision/input conditioning

The hardware abstractions are intentionally safe/no-op in development until real pin maps and deployment hosts are connected.
