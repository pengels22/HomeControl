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
| PNL module agent | Partial | State/config agent only |
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

1. Run final documentation review and merge the white-paper branch.
2. Explicitly identify the Linux I2C bus on the RCM bench target.
3. Place a bench RCM profile into BENCH_TESTING outside repository defaults.
4. Run the single selected-channel HIL relay test with a meter/LED/test load.
5. Advance to RCM module commissioning only after successful bench evidence.
6. Repeat a controlled process for LCM.
7. Commission physical HCM fire GPIO separately.

## Channel registry extension

See [channel metadata, rooms, HVAC semantics and bridges](CHANNEL_METADATA_AND_BRIDGES.md)
for migration 008, the shared editor, safety compatibility, and optional bridge
transports. Software checks do not establish physical commissioning, MQTT broker
connectivity, or Matter fabric acceptance.
