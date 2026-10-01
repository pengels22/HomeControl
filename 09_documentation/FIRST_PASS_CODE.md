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
- HCM deployment-ready web UI scaffold
- macOS full-system simulator on port 8088
- HVAC state machine using pinned timings and global mode/setpoint
- life-safety fire controller path
- update service skeleton on TCP 6503
- per-module local web UI scaffolds with HCM-token authentication expectation
- RCM simulator controls for 32 relays, maintenance locks, and editable channel names
- LCM simulator controls for relay names, low-voltage dimming fade targets, and high-voltage dimmer status
- 3.3-inch HCM screen mockup with secure QR pairing code inside the circular pairing UI
- iOS companion app prototype with standard-code scanning, circular-code camera scanning, HCM login, and simulator loading
- secure circular pairing payloads using opaque `HC2` tokens verified by HCM
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
- production-grade visual treatment for the circular pairing UI around the scanner-compatible QR
- production crypto provider for pairing payload encryption, replacing the current standard-library simulator implementation
- final rules schema/executor
- final PNL UI
- OTA/app package deployment logic
- production life-safety GPIO supervision/input conditioning

The hardware abstractions are intentionally safe/no-op in development until real pin maps and deployment hosts are connected.
