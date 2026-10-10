# HCM Architecture Conflicts

> **Status note (2026-10-10):** This document is a historical **conflict inventory**, not a list of unresolved decisions. The actual Jetson development deployment was verified on 2026-10-10; VLAN 20 remains current, VLAN 40 production control and VLAN 60 heartbeat migrations remain pending. Consult the [Jetson deployment runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md) before treating any legacy addresses or implementation conflicts below as live facts.


This document lists contradictions between existing repository specifications,
current implementation, and the newer architecture brief. Do not resolve these
silently in code.

## 1. VLAN 60 Purpose

Original repository baseline:

- VLAN 60 is the HCM control network.
- HCM/router is `192.168.60.1`.
- RCM, LCM, SIM, and PNL use `.20+` pools.
- Module configs use HCM host `192.168.60.1`.
- HCM registry assigns module IPs in `192.168.60.0/24`.

Current repository correction:

- Module configs use VLAN 20 HCM host `192.168.20.27`.
- HCM registry assigns from configured control-network profiles.
- The active template profile is VLAN 20 development/control.
- VLAN 60 is rejected as a module-control assignment profile.

Decided target architecture:

- VLAN 60 is heartbeat/supervisory-only traffic between modules/devices and the
  Conflict Manager.
- Conflict Manager uses `192.168.60.2`.
- Current development heartbeat baseline remains VLAN 20.

Risk:

- Treating VLAN 60 as both general module control and heartbeat-only can break
  commissioning, routing, firewall rules, and module assumptions.

Remaining recommendation:

- Keep the repo's original VLAN 60 module-control assumptions deprecated.
- Do not enable VLAN 40 assignment until an approved production subnet, DHCP
  plan, and firewall policy exist.
- Keep VLAN 60 restricted to heartbeat/supervisory traffic. Do not add normal
  app/module control, update downloads, web UI, or database traffic to VLAN 60.

## 2. HCM Address Versus Conflict Manager VLAN Interface

Original repository:

- HCM owns `192.168.60.1`.
- Module pools begin at `.20`.

Approved architecture:

- Conflict Manager future `eth0.60` is `192.168.60.2/24`.

This is not inherently an IP conflict, but it is a purpose conflict because VLAN
60 is heartbeat-only. The gateway/router role of HCM at `.1` must be replaced
or redefined; HCM should not remain the normal module-control endpoint on VLAN
60.

Remaining recommendation:

- Define whether HCM has any heartbeat-only presence on VLAN 60, and if so what
  address it uses.
- Keep module-control addressing off VLAN 60 through the configurable network
  profile model.

## 3. Persistent TCP/TLS Module Heartbeat Versus Unified Heartbeat V3

Existing implementation:

- Linux modules connect persistently to HCM TCP 6501.
- They send module `heartbeat` messages and receive `heartbeat_ack`.
- HCM records `last_seen`, `last_state`, and online/offline state in PostgreSQL.
- Optional TLS exists for module TCP.

Newer brief:

- Unified Heartbeat V3 is authoritative for processor heartbeat.
- Do not reintroduce older separate ACK daemons or competing heartbeat services.
- Every participating processor should run one unified heartbeat daemon.

Risk:

- Two heartbeat concepts can produce inconsistent health status, stale healthy
  displays, duplicated alerts, and ambiguous ownership of device registration.

Recommendation:

- Preserve TCP 6501 as command/state/config transport.
- Make Unified Heartbeat V3 the network-wide processor supervision plane.
- Have Linux module agents report subsystem state/faults/watchdogs to the local
  V3 Unix socket instead of spawning another heartbeat.
- Rename or scope TCP 6501 `heartbeat` frames as session liveness/module-state
  updates, not supervisory health authority.
- Add documentation and tests showing how HCM combines PostgreSQL module state
  and V3 supervision without making either silently override the other.

## 4. Fire Input Polarity

Existing pinned documentation:

- Fire input HIGH = normal.
- Fire input LOW = fire active.

Newer brief:

- Latest SPDT arrangement: NO -> 3.3 V, Common -> GPIO, NC -> Ground.
- Assuming normally de-energized relay: normal LOW, alarm HIGH.

Risk:

- Implementing the wrong polarity could invert fire behavior.

Recommendation:

- Freeze fire GPIO driver work until actual relay wiring and electrical behavior
  are tested.
- Update `PINNED_ARCHITECTURE.md`, HCM pinout, safety docs, and tests only after
  the authoritative hardware specification is chosen.
- Include debounce and loss-of-wire analysis in the same decision.

## 5. Maintenance Lockout And Life Safety

Existing repository:

- Priority order places Maintenance Lock above Life Safety.
- Code blocks commands to maintenance-locked logical devices.
- Fire light sweep filters out `maintenance_locked=true`.

Approved architecture:

- Maintenance lockout is part of life-safety architecture.
- Maintenance lockout is the highest-priority output inhibit.
- No controlled output may energize while maintenance lockout is active,
  including during fire response.
- Fire detection, logging, fault reporting, and communication continue where
  possible.

Risk:

- Current code blocks logical-device commands but does not yet provide a
  complete final-state arbitration layer proving that no lower-level driver
  receives an energize command while maintenance lockout is active.

Recommendation:

- Preserve priority order: Maintenance Lockout, Fire/Life Safety, Local
  Override, HCM Rules/User Commands.
- Add requested-state versus final-state safety arbitration.
- Add tests for maintenance lockout during normal commands, local overrides,
  rules, and simulated fire alarms.
- Document relay contact states and required hardwired interlocks before
  hardware validation.

## 6. Device Registration And Identity

Existing module registry:

- Uses `module_uuid` derived from module type and machine ID.
- Assigns hostname/IP by module type.
- Stores modules in PostgreSQL.

Approved identity architecture:

- Uses the designated physical interface MAC as the authoritative `device_id`.
- Normalizes by lowercasing and removing colons.
- The ID is 12 hexadecimal characters, not a 128-bit UUID.
- Generated module UUIDs are replaced by the normalized device ID.

Risk:

- Current PostgreSQL schema, module registry, tests, and module agent still use
  `module_uuid` UUID semantics.
- Current Heartbeat V3 code still emits colon-form MACs.
- A destructive migration could orphan device bindings, faults, history, and
  assignments.

Recommendation:

- Add a staged, non-destructive database migration from `module_uuid` to
  `device_id`.
- Backfill existing rows with reviewed mappings.
- Keep legacy identifiers until all foreign keys, bindings, faults, firmware
  updates, config history, and tests are migrated.
- Normalize Heartbeat V3 `device_id`, `allowed_device_ids`, and
  `conflict_device_id`.
- Document recommissioning for changed physical network interfaces.

## 7. Heartbeat State Names

Architecture brief:

- Distinguish `healthy`, `degraded`, `faulted`, and `offline`.

Current V3 implementation:

- Local `health.state` is `healthy` or `fault`.
- Local `status.state` is `operational` or `degraded`.
- Peer reachability is `online` boolean with age.

Risk:

- UI and alerting may need translation logic and could display local faulted and
  peer offline states inconsistently.

Recommendation:

- Define a presentation mapping without breaking the Python 3.6 V3 wire format
  abruptly.
- Consider a protocol-compatible future field or documented UI state derivation.

## 8. CAN Bitrate

Repository config conflict:

- `06_config/02_SIM/sim.yaml` uses default CAN bitrate 125000.
- `06_config/06_RMC/rmc.yaml` says RMC CAN speed is 250000.
- `06_config/06_RMC/RMC.ino` defines `RMC_CAN_SPEED CAN_250KBPS`.

Risk:

- SIM and RMC will not communicate on real hardware if bitrates differ.

Recommendation:

- Choose one bitrate after hardware validation.
- Update SIM config, RMC YAML, RMC firmware constants, and tests together.

## 9. LCM Fade Ownership

Existing docs:

- Low-voltage dimmer slider-originated commands should fade over 3 seconds.

Current implementation:

- Simulator implements fade tasks.
- LCM module applies dimmer commands immediately.

Risk:

- Production behavior may differ from simulator behavior.

Recommendation:

- Decide whether fade is owned by HCM/UI command generation, LCM agent, or both
  with explicit command metadata.
- Add tests at the chosen ownership boundary.

## 10. TLS And Authentication Claims

Existing docs:

- Module communication says persistent TCP with TLS authentication.

Current implementation:

- TLS is optional and disabled by module configs.
- Mutual TLS support exists but certificate provisioning is not implemented.
- Module web UI authenticates status through HCM bearer tokens.

Risk:

- Docs may imply stronger authentication than deployment currently provides.

Recommendation:

- Document current default as development/integration mode.
- Require TLS and client identity before production module deployment.
- Keep app/iOS control through HCM only.

## 11. PostgreSQL Authority Versus YAML Config

Existing code:

- PostgreSQL stores authoritative modules, bindings, logical devices, and HVAC.
- YAML files define module defaults, pinouts, ports, IO mode, and hardware
  manifests.

Risk:

- Everyday configuration could drift between YAML and PostgreSQL if ownership is
  not formalized.

Recommendation:

- Treat YAML as deploy-time hardware/module defaults and PostgreSQL as runtime
  authority for logical device mapping and user configuration.
- Record pushed YAML-derived configs in `configuration_history`.
- Avoid hardcoding device-specific addresses in application logic.

## 12. Safety Event Persistence

Current code:

- Inserts `safety_events`, but `fire_active` is in memory.

Risk:

- HCM restart during or after a fire event may not restore latched state without
  a hardware input driver or persisted active-state reconstruction.

Recommendation:

- Once fire input hardware is defined, derive active fire state from the input
  and persist/audit transitions.
- Define operator reset/clear semantics explicitly.
