# HomeControl Implementation Status

**Audited baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`
**Hosted ACM CI:** successful on the synchronized baseline

## Status definitions

- **Implemented / tested** — software path exists and is covered by automated tests.
- **Implemented / deployment-unverified** — software exists but target deployment has not been fully verified.
- **Implemented / hardware-unverified** — real transport path exists but physical hardware has not been commissioned.
- **Simulated / mock only** — behavior is exercised without real hardware.
- **Partial** — substantial scaffolding exists but required behavior remains missing.
- **Planned** — design exists without an operational implementation.
- **Superseded** — older design no longer represents the approved architecture.

## System matrix

| Subsystem | Status | Current truth |
|---|---|---|
| HCM FastAPI/API | Implemented / tested | Real application runtime |
| PostgreSQL persistence | Implemented / tested | Explicit migration tooling now exists |
| Password login | Implemented / tested | PBKDF2 + persistent DB sessions |
| Touchscreen PIN auth | Implemented / tested | Device tokens, scrypt PINs, permissions |
| WebAuthn/passkeys | Partial | Production assertion verifier not implemented |
| Logical devices/bindings | Implemented / tested | Single enabled binding enforced |
| Physical execution binding | Implemented / tested | Durable `execution_mode` controls physical request |
| Output arbitration | Implemented / tested | Maintenance, life safety, override, normal intents |
| HVAC algorithm | Implemented / tested | Heat/cool/fan/off, minimum run and restart locks |
| HVAC fire shutdown | Implemented / tested | Best-effort OFF attempts across all three calls |
| System maintenance lockout | Implemented / tested | Separate from logical-device lockout |
| Fire simulation path | Implemented / tested | Disabled when physical input is authoritative |
| Physical fire GPIO | Implemented / hardware-unverified | Linux gpiod backend exists; not commissioned |
| Emergency-light selection | Implemented / tested | Metadata/explicit list; not “all lights” |
| Critical mobile delivery | Partial | Notification persisted; delivery adapter absent |
| Rules engine | Planned/partial | Loop/status exists; generalized execution disabled |
| Module registry TCP | Implemented / tested | Persistent command/state/config sessions |
| Module event delivery | Implemented / tested | Offline queue + HCM log ACK round-trip |
| Module mTLS | Implemented / deployment-unverified | Supported but not enabled in dev defaults |
| RCM software agent | Implemented / tested | Full 32-channel model |
| RCM XL9535 driver | Implemented / hardware-unverified | Real Linux I2C path exists |
| RCM bank selection and local override latch | Implemented / tested / hardware-unverified | MCP1/MCP2 active-low inputs, 250 ms debounce, 5 s timeout, conflict/startup interlocks; physical behavior still requires HIL |
| RCM safe-off | Implemented / tested | Safety and all_off command real driver OFF |
| LCM relay driver | Implemented / hardware-unverified | MCP23017 path exists |
| LCM 0-10 V driver | Implemented / hardware-unverified | PCA9685 path exists |
| LCM Shelly driver | Implemented / identity-uncommissioned | RPC path exists; endpoints not commissioned |
| LCM safe-off | Implemented / tested | Relays/PWM/Shelly attempted independently |
| SIM SocketCAN receive | Implemented / deployment-unverified | Real AF_CAN receive lifecycle exists |
| RMC telemetry decoder | Implemented / tested | Includes staleness/online tracking |
| SIM analog input | Partial | Configuration/model exists; physical adapter incomplete |
| SIM DIO | Partial | Direction/state model exists; physical adapter incomplete |
| SIM switched 12 V | Partial | State model exists; physical mapping/adapter incomplete |
| RMC physical firmware update | Planned | Explicitly fails closed |
| PNL module agent | Implemented / deployment-unverified | PostgreSQL-backed registration, published dashboard delivery, telemetry, bounded state resync, commands, occupancy, and Sonic policy APIs; ESP32/P4 transport remains unverified |
| Unified Heartbeat V3 | Implemented / tested | HMAC, replay rejection, SQLite registry |
| Conflict Manager | Implemented / deployment-validated in dev scope | Independent supervisor |
| Generic update trust | Implemented / tested | HMAC + Ed25519 + SHA256 + replay store |
| Update installers | Partial | Trust envelope stronger than target-specific physical installers |
| ACM alarm state machine | Implemented / tested | Standalone-first global alarm authority; Home/Away, delays, bypass, FAULT, and Panic paths |
| ACM local sensors | Implemented / hardware-unverified | 24 inputs, pull-up polarity, stable 250 ms debounce |
| ACM remote keypad supervision | Implemented / hardware-unverified | Up to 7 keypads, 30 s heartbeat, ~90 s FAULT, identity and snapshot reconnect |
| ACM credential storage | Implemented / tested | Master/Standard PIN records, PBKDF2-HMAC-SHA256, reprovision path |
| ACM alarm relays | Implemented / hardware-unverified | Eight active-low outputs with safe boot intent and siren policy |
| ACM keypad siren/piezo | Implemented / hardware-unverified | 5 V siren reconciliation and nonblocking delay chirps |
| ACM embedded web administration | Implemented / software-tested | Master-only local HTTP administration, bounded and CSRF-protected |
| ACM SD logging | Implemented / hardware-unverified | Unsynced and monthly local-time logs with bounded web tail |
| ACM HCM time synchronization | Implemented / deployment-unverified | HCM supplies time; ACM forwards synchronized time to keypads |
| ACM HCM compact status integration | Implemented / deployment-unverified | Compact `ACM_STATUS`; HCM is not alarm authority |
| ACM keypad UI model/controller | Implemented / tested | Shared numeric keypad geometry and semantic action controller |
| ACM LCD/touch physical renderer | Partial / hardware pending | Concrete renderer remains behind the display boundary until hardware is confirmed |
| ACM HIL commissioning | Not yet performed | Software baseline is `ACM_V1_READY_FOR_HIL` |
| Hardware-in-loop tests | Gated / not yet run on field hardware | Explicit opt-in only |
| GitHub branch protection | Not configured | `main` currently unprotected |

## Current safe defaults

PNL production APIs treat each panel as a separately authenticated client. HCM
selects published dashboards by explicit panel assignment, then area, then a
shared published dashboard, with a bounded local fallback. Panel-local sensor
aliases remain relative to the panel; remote commands continue through HCM's
logical command authority. The panel event endpoint is bounded and supports
resynchronization; it does not replace Unified Heartbeat V3.

Repository defaults intentionally inhibit physical actuation:

- `io.mode: auto` resolves to simulated;
- RCM/LCM `physical_output_enabled: false`;
- output sections `real_output_enabled: false`;
- hardware profiles are not committed as COMMISSIONED;
- real I2C requires explicit Linux bus mapping;
- physical RMC firmware updates return not implemented;
- no automatic HIL output loop is run by CI.

## Network truth

Current development/control and heartbeat traffic uses VLAN 20.

- HCM: `192.168.20.27`
- Conflict Manager: `192.168.20.26`
- Heartbeat port: TCP 6004
- CAN: 125000 bit/s

VLAN 60 references in older documents are superseded.

VLAN 40 remains a future production control-network placeholder without an approved subnet.

## Commissioning truth

Commissioning is per module.

There is no production `commissioned_channels` list.

Normal physical energization requires COMMISSIONED module status plus all physical-enable gates.

BENCH_TESTING is valid only for the separate explicit hardware-test harness.

## Safety truth

Fire input:

- relay NO -> 3.3 V;
- relay C -> GPIO;
- relay NC -> GND;
- normal LOW;
- alarm HIGH;
- transition debounce 250 ms.

A physical authoritative fire input cannot be overridden by the software simulation endpoint.

System maintenance lockout inhibits emergency actuation without erasing fire detection.

Logical-device maintenance lockout applies only to the selected logical output.

Safety deenergization is allowed to command initialized real hardware OFF even when normal energization permission is unavailable.

## Next recommended milestones

The current immediate milestone is `ACM_V1_READY_FOR_HIL`:

1. Freeze ACM V1 software at the audited baseline unless HIL exposes a defect.
2. Begin ACM boot/output-safety validation.
3. Validate ACM W5500 Ethernet, identity, web administration, and HCM connection/time synchronization.
4. Validate SD logging and power-cycle behavior.
5. Validate ACM MCP/I2C and all 24 local inputs.
6. Validate all 8 ACM relay outputs and siren policy.
7. Bring up and enroll one physical ACM keypad.
8. Validate keypad inputs, Panic, piezo, 5 V siren, heartbeat/offline FAULT, and reconnect snapshot.
9. Execute the complete ACM Home/Away/failure HIL scenario set documented in `COMMISSIONING_AND_VALIDATION.md`.
10. Record HIL evidence and only then classify ACM physical commissioning status.
11. Resume the existing controlled RCM/LCM commissioning sequence afterward.

## Channel registry extension

See [channel metadata, rooms, HVAC semantics and bridges](CHANNEL_METADATA_AND_BRIDGES.md)
for migration 008, the shared editor, safety compatibility, and optional bridge
transports. Software checks do not establish physical commissioning, MQTT broker
connectivity, or Matter fabric acceptance.
