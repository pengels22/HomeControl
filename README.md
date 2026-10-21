# HomeControl

HomeControl is a local-first distributed home/building control platform centered on the **HCM (Home Control Manager)**.

The current audited software baseline is:

- Commit: `6fc4179c3a2671fc66c81dc9f69d320ee2420f8f`
- Hosted CI: HomeControl CI run `39183220588` — success
- Full test suite at that baseline: **536 passed, 10 skipped**

## Authoritative documentation

Start here:

- [White-paper index](10_documentation/whitepapers/README.md)
- [System architecture](10_documentation/whitepapers/HOMECONTROL_SYSTEM_WHITE_PAPER.md)
- [Implementation status](10_documentation/whitepapers/IMPLEMENTATION_STATUS.md)
- [Life-safety and arbitration](10_documentation/whitepapers/LIFE_SAFETY_AND_ARBITRATION.md)
- [Network and heartbeat](10_documentation/whitepapers/NETWORK_AND_HEARTBEAT.md)
- [Hardware modules and I/O](10_documentation/whitepapers/HARDWARE_MODULES_AND_IO.md)
- [Security, authentication, and updates](10_documentation/whitepapers/SECURITY_AUTH_AND_UPDATES.md)
- [Commissioning and validation](10_documentation/whitepapers/COMMISSIONING_AND_VALIDATION.md)
- [Glossary](10_documentation/whitepapers/GLOSSARY.md)

Where older dated material conflicts with the white papers or current source, the white papers and audited source are authoritative.

## Current architecture

Core roles:

- **HCM** — central API, PostgreSQL-backed control authority, logical-device mapping, HVAC, safety orchestration, authentication, updates, and management.
- **RCM** — 32-channel relay control module.
- **LCM** — lighting module with relay outputs, ten 0-10 V outputs, and four Shelly high-voltage dimmer channels.
- **SIM** — sensor/CAN gateway.
- **RMC** — CAN room-monitoring microcontroller node.
- **PNL** — panel agent / wall-interface role.
- **Conflict Manager** — independent Heartbeat V3 supervisor.

## Network baseline

Current development/control and heartbeat traffic uses **VLAN 20**.

Known current addresses:

- HCM/Jetson Ethernet: `192.168.20.27`
- HCM/Jetson Wi-Fi: `192.168.20.25`
- Conflict Manager Ethernet: `192.168.20.26`
- Conflict Manager Wi-Fi: `192.168.20.24`
- LAB1: `192.168.20.36`

Heartbeat uses TCP 6004.

VLAN 40 remains a future production-control placeholder. VLAN 60 is not part of the current approved architecture.

## CAN baseline

RMC/SIM CAN is **125000 bit/s**.

## Safety baseline

FIRE dry-contact input:

- NO -> 3.3 V
- C -> GPIO
- NC -> GND
- normal = LOW
- alarm = HIGH
- transition debounce = 250 ms

System maintenance lockout and per-logical-device maintenance lockout are separate concepts.

Physical fire state remains authoritative when the Linux GPIO backend is enabled.

## Commissioning model

Commissioning is **module-level**.

Normal physical output requires:

1. real I/O mode;
2. module status `COMMISSIONED`;
3. `physical_output_enabled: true`;
4. a channel present in the authoritative hardware profile;
5. the relevant output section `real_output_enabled: true`;
6. safety/maintenance authorization;
7. a physical HCM binding.

`BENCH_TESTING` is reserved for explicit HIL tooling and does not enable ordinary HCM/module API physical writes.

Repository defaults remain nonphysical.

## Repository layout

- `00_Heartbeat` — Unified Heartbeat V3
- `01_HCM` — Home Control Manager
- `02_SIM` — Sensor Interface Module
- `03_LCM` — Lighting Control Module
- `04_RCM` — Relay Control Module
- `05_PNL` — Panel Module
- `07_config` — hardware/config/deployment manifests
- `08_servises` — shared/system services (spelling retained by project)
- `09_database` — PostgreSQL schema and migrations
- `10_documentation` — current runbooks, pinout, and white papers
- `11_scripts` — simulators, deployment, and admin tooling
- `12_tests` — automated software tests
- `13_hardware_tests` — explicitly gated HIL tests

## Current readiness

The software baseline is ready for:

- documentation freeze;
- controlled single-channel RCM bench testing.

It is **not** a claim that the installed physical system is commissioned.

Known physical gaps remain documented in the implementation-status and commissioning white papers.
