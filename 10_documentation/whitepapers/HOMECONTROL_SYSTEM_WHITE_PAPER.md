# HomeControl System White Paper

**Status:** Draft authoritative architecture
**Audited software baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`
**Hosted ACM CI:** successful on the synchronized baseline

## 1. Purpose

HomeControl is a local-first distributed building and home control platform. Its design separates central decision-making, field I/O, room sensing, wall interfaces, and independent supervision into distinct components while keeping safety-related behavior explicit and fail-closed.

The system is designed around five principles:

1. logical devices rather than raw hardware addresses;
2. local operation without cloud dependency;
3. explicit authority and safety arbitration;
4. modular hardware with independently supervised processors;
5. truthful distinction between commanded state, device-reported state, and physically verified state.

This paper describes the architecture actually represented by the audited repository. It deliberately distinguishes implemented behavior from hardware that remains uncommissioned or planned.

## 2. Core Components

### ACM — Alarm Control Module

ACM is the standalone-first security alarm controller implemented on ESP32-S3
hardware. It is the authority for security alarm operation; HCM receives only
compact global ACM status and time/status integration. ACM provides 24 local
alarm inputs, up to 7 enrolled PoE keypads with 8 inputs each, and 80 logical
sensor slots total (`24 + 7×8`). It also provides 8 active-low relay outputs,
local embedded HTTP administration, and SD event logging.

ACM retains alarm operation when HCM is unavailable. HCM loss does not prevent
arming, disarming, entry delay, alarm triggering, siren operation, or physical
keypad Panic. Panic is a physical keypad input only; there is no touchscreen
Panic action. ACM Areas are organizational/display metadata, not alarm
partitions. Each local sensor and keypad belongs to exactly one Area, all eight
inputs inherit the keypad Area, and multiple keypads may share an Area.

The ACM state model is `DISARMED`, `ARMING_DELAY`, `ARMED_HOME`, `ARMED_AWAY`,
`ENTRY_DELAY`, `TRIGGERED`, and `TROUBLE`. Home arm is immediate with opening
sensors active and motion ignored. Away arm enters a 30-second arming delay;
sensors are ignored during that delay, opening starts a 30-second entry delay,
and motion must remain active for 10 continuous seconds before entry delay.
An open sensor never blocks arm: it is bypassed until it closes once, then
becomes active normally. FAULT represents an unavailable sensor/device and is
distinct from OPEN; it does not itself trigger an alarm.

### HCM — Home Control Manager

HCM is the central application authority.

Implemented HCM responsibilities include:

- FastAPI REST API and browser UI;
- PostgreSQL-backed users, sessions, modules, logical devices, bindings, HVAC state, faults, safety events, firmware metadata, and related configuration;
- module registry and persistent control sessions;
- logical-device command routing;
- output intent and priority arbitration;
- HVAC control logic;
- fire/life-safety orchestration;
- system and per-device maintenance lockouts;
- configuration synchronization;
- update orchestration;
- touchscreen authentication and authorization;
- module state and fault ingestion.

HCM is not itself the independent heartbeat supervisor. Unified Heartbeat V3 remains a separate process so HCM application failure does not eliminate supervisory visibility.

### RCM — Relay Control Module

RCM provides general-purpose relay outputs.

Authoritative channel inventory:

- A1-A8
- B1-B8
- C1-C8
- D1-D8

The audited software contains a production-shaped real path:

HCM logical binding -> physical execution request -> module commissioning gate -> XL9535 relay driver -> Linux I2C transport.

Physical output remains disabled in repository defaults. RCM safety handling can command known initialized real outputs OFF independently of normal energizing permission.

### LCM — Lighting Control Module

LCM provides lighting control across three output classes:

- relay outputs A1-A8;
- 0-10 V dimming outputs 10-1 through 10-10;
- high-voltage dimming outputs HV-1 through HV-4.

The active software architecture supports:

- MCP23017 relay outputs;
- PCA9685 PWM-based 0-10 V control;
- Shelly RPC high-voltage dimmer control;
- canonical channel normalization;
- local safe-off behavior across all configured output classes.

Physical output remains disabled pending commissioning.

### SIM — Sensor Interface Module

SIM is the field sensor/CAN gateway.

Implemented responsibilities include:

- Linux SocketCAN receive transport;
- CAN interfaces can0, can1, and can2;
- RMC telemetry decoding;
- RMC online/stale tracking;
- simulated Hexa analog, digital, USB, and switched-12 V state;
- RMC firmware update simulation;
- fail-closed rejection of physical RMC firmware updates until a real bootloader transport exists.

All active RMC/SIM CAN configuration is 125000 bit/s.

Physical Hexa ADC, DIO, and switched-12 V adapters remain incomplete.

### RMC — Room Monitoring Cluster

RMC is the CAN-connected room sensor node.

The repository defines the RMC sensor and telemetry architecture, including temperature/humidity, air-quality, ambient-light, presence, heartbeat, fault, and update protocol concepts.

Physical RMC firmware update transport remains intentionally incomplete. The software does not falsely report a physical update as successful.

### PNL — Panel Module

PNL represents a room/wall panel agent.

The current PNL agent manages:

- room assignment;
- dashboard URL;
- refresh settings;
- brightness configuration;
- authentication requirement.

The complete LCD/touch/browser runtime is separate from the minimal PNL agent and should not be considered fully implemented solely because `05_PNL/main.py` is present.

### Conflict Manager

The Conflict Manager is an independent supervisory processor.

Unified Heartbeat V3 can run in Conflict role and provides:

- authorized-device registry;
- HMAC-authenticated heartbeat request/response;
- stable MAC-derived device identity;
- boot ID and sequence tracking;
- replay rejection;
- duplicate-device detection;
- current online/offline state;
- communication-loss fault lifecycle;
- SQLite persistence.

Conflict supervision is independent of HCM's PostgreSQL application state.

## 3. Network Architecture

### Current development/control network

The active development and supervision network is VLAN 20.

Known current addresses include:

- HCM/Jetson Ethernet: `192.168.20.27`
- Conflict Manager Ethernet: `192.168.20.26`

Heartbeat supervision currently also operates over VLAN 20.

### Future production control network

VLAN 40 is reserved as the future production control network in configuration, but its final subnet and address pools are not approved and must not be invented.

### Superseded VLAN 60 plan

VLAN 60 is not part of the current approved architecture.

Historical documents that describe VLAN 60 heartbeat traffic or Conflict at `192.168.60.2` are superseded by the current VLAN 20 heartbeat architecture.

### Control protocols

The principal communication planes are:

- HCM API: HTTP/REST;
- HCM <-> Linux modules: persistent TCP 6501 using length-prefixed JSON;
- Unified Heartbeat V3: TCP 6004 using HTTP with HMAC authentication in the current secured configuration;
- SIM <-> RMC: Classical CAN at 125000 bit/s;
- local module <-> heartbeat daemon: Unix domain socket.

## 4. Device Identity

The preferred stable device identifier is the MAC address of a designated physical network interface, normalized to lowercase hexadecimal without separators.

Example:

`48:b0:2d:87:db:16` -> `48b02d87db16`

The identity interface is documented separately from whichever interface happens to carry heartbeat or application traffic.

Hostnames remain human-readable operational names and are not the identity authority.

## 5. Logical Device Model

Normal application control targets logical devices rather than hardware channels.

A logical device binding associates:

- logical device;
- module;
- module channel;
- metadata;
- execution mode.

The binding's durable `execution_mode` is either:

- `simulated`
- `physical`

Only a durable physical binding causes HCM to request physical execution. A command payload cannot upgrade a simulated binding to physical execution.

The module independently rechecks its own commissioning and hardware authorization before performing a physical write.

Ambiguous multiple enabled bindings are rejected rather than silently selecting the first one.

## 6. Commissioning Model

Commissioning is module-level, not channel-level.

The module lifecycle is:

- UNVERIFIED
- DESIGN_APPROVED
- BENCH_TESTING
- BENCH_TESTED
- COMMISSIONED
- SIMULATED, where applicable

Normal production physical energization requires all of the following:

1. real I/O mode;
2. module status COMMISSIONED;
3. `physical_output_enabled: true`;
4. requested channel present in the authoritative hardware profile;
5. output section `real_output_enabled: true`;
6. safety arbitration permits the requested energized state.

There is no normal per-channel commissioning allowlist.

BENCH_TESTING does not permit ordinary module API or HCM commands to actuate hardware. Bench actuation is limited to explicit HIL tooling with exact module and channel selection.

## 7. Safety and Output Priority

The practical authority order is:

1. maintenance lockout;
2. fire/life safety;
3. local override;
4. normal user/rules/schedule intents.

Two distinct maintenance concepts exist:

### System life-safety maintenance lockout

This is maintained by the HCM safety controller. It is intended for system wiring/testing maintenance and can inhibit life-safety output actuation without erasing fire detection or status.

### Logical-device maintenance lockout

This applies to an individual logical device and prevents that output from energizing.

Both must remain separate.

### Safe-off principle

Authorization to energize and authority to deenergize are intentionally asymmetric.

A known initialized real driver may always be commanded toward its defined safe OFF state by local safety handling even when normal energizing authorization is unavailable.

One output failure must not prevent attempts to deenergize later outputs.

## 8. Fire/Life-Safety Architecture

The current fire input model uses dedicated dry-contact relay inputs.

Authoritative FIRE wiring:

- NO -> 3.3 V
- C -> GPIO
- NC -> GND

Assuming the smoke relay is normally deenergized:

- normal = LOW
- alarm = HIGH

Input transitions use a 250 ms software debounce.

When the physical fire backend is authoritative, the software simulation API cannot clear or override the physical state.

Fire response:

- records the fire event;
- reports supervisory status/fault;
- initiates HVAC shutdown;
- commands only designated emergency-lighting logical devices when system maintenance lockout permits;
- records a critical notification event.

The system does not assume that a command acknowledgement proves physical load state.

The current notification adapter persists notification records but does not yet deliver production mobile push notifications.

There is no software fire latch that overrides the physical contact. The physical relay remains the authority.

## 9. HVAC Architecture

HCM acts as the thermostat.

Supported modes:

- HEAT
- COOL
- FAN
- OFF

Implemented sequence:

1. command required dampers;
2. wait configured damper lead;
3. fan ON;
4. wait configured fan lead;
5. heat or cool call ON.

Current defaults:

- 1 F deadband;
- cooling minimum run: 2 minutes;
- heating minimum run: 1 minute;
- cooling restart lockout: 5 minutes;
- heating restart lockout: 5 minutes;
- fan post-run: 60 seconds.

Fire/life-safety `force_off()` attempts COOL, HEAT, and FAN OFF independently so one failed command does not prevent attempts on the remaining outputs.

There is no master software-controlled HVAC disconnect relay in the current architecture.

## 10. Heartbeat and Supervision

Unified Heartbeat V3 is the network-wide supervisory service.

Each heartbeat includes at least:

- protocol/version;
- hostname;
- stable device ID;
- identity interface;
- boot ID;
- sequence number;
- timestamp;
- local health;
- local status.

Conflict validates authorization, HMAC, timestamp, sequence progression, source continuity, and duplicate identity conditions.

The HCM/module TCP heartbeat is separate and serves control-session liveness/state exchange. It does not replace Conflict supervision.

## 11. Authentication and Security

Implemented authentication includes:

- PostgreSQL-backed users;
- PBKDF2 password hashes;
- persistent bearer sessions;
- current user role/enabled-state validation;
- login lockout/rate limiting;
- touchscreen device authentication;
- six-digit touchscreen PINs protected with scrypt;
- touchscreen VIEWER/CONTROL/ADMIN permission levels;
- pairing-key infrastructure.

Production WebAuthn/passkey assertion verification is not yet implemented. The API intentionally returns an unavailable/not-implemented result rather than simulating production verification.

The module transport supports mTLS and certificate identity checking, but current development YAML defaults do not enable TLS. Production deployment must provision and enable certificate-backed module identity rather than relying on lab plaintext settings.

## 12. Update Security

The generic module update envelope supports:

- HMAC request authentication;
- timestamp checking;
- durable operation replay protection;
- SHA-256 artifact integrity;
- Ed25519 signatures;
- module target validation;
- hardware revision validation;
- staging-root confinement;
- fixed trusted installer selection.

Post-update HCM verification requires a heartbeat newer than the pre-update state and validates expected software version where supplied.

Physical RMC CAN firmware update remains blocked until the RMC bootloader and ACK/NACK transport are implemented and verified.

## 13. Database and Persistence

PostgreSQL is the central HCM application database.

The repository now uses an explicit migration runner:

- `homecontrol-db status`
- `homecontrol-db migrate`

Normal HCM startup does not silently perform schema migration.

Module configuration and event queues also use local persistent files where needed for disconnected operation.

Conflict Manager supervision uses its own SQLite registry and remains independent of PostgreSQL.

## 14. Current Test Meaning

The automated suite proves software contracts, not installed electrical behavior.

Normal CI primarily exercises:

- simulation;
- mock production drivers;
- database contracts;
- API behavior;
- safety arbitration;
- hardware authorization;
- CAN transport abstraction;
- updater security;
- migration logic.

Hardware-in-the-loop tests are separately gated and must be explicitly enabled.

A green CI run must not be described as physical commissioning.

## 15. Known Incomplete Areas

The following remain intentionally incomplete or uncommissioned:

- physical SIM ADS1115 input implementation;
- physical SIM Hexa DIO;
- physical SIM switched 12 V;
- RMC physical CAN bootloader/update transport;
- final Shelly device identity/endpoints;
- production WebAuthn verification;
- production mobile/watch notification delivery;
- generalized rules/scenes/schedule execution;
- full PNL display/touch runtime integration;
- real RCM/LCM/Fire HIL commissioning;
- production mTLS deployment across all module sessions;
- branch protection enforcement on GitHub.

## 16. Readiness Statement

At the audited baseline, HomeControl is best described as:

**a software-complete distributed control framework with production-shaped physical RCM/LCM/CAN pathways, strong safety gating, independent supervision, and uncommissioned field hardware.**

The next hardware milestone is a controlled single-channel RCM bench test using explicit real I2C configuration and a safe test load.

## Channel registry extension

See [channel metadata, rooms, HVAC semantics and bridges](CHANNEL_METADATA_AND_BRIDGES.md)
for migration 008, the shared editor, safety compatibility, and optional bridge
transports. Software checks do not establish physical commissioning, MQTT broker
connectivity, or Matter fabric acceptance.
