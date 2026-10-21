# HomeControl Glossary and Acronyms

This glossary defines terms as they are used in the current HomeControl architecture. Historical project documents may use some names differently.

## Core project acronyms

| Term | Meaning | HomeControl usage |
|---|---|---|
| **HCM** | **Home Control Manager** | Central application controller, API, database authority, HVAC controller, device manager, and safety orchestrator. Historical documents sometimes called it “House Control Module”; the current white papers use Home Control Manager. |
| **RCM** | Relay Control Module | Linux field module providing 32 relay outputs A1-D8. |
| **LCM** | Lighting Control Module | Linux field module providing relay, 0-10 V, and high-voltage dimming outputs. |
| **SIM** | Sensor Interface Module | Linux sensor/CAN gateway between HCM and field sensor/RMC networks. |
| **RMC** | Room Monitoring Cluster | CAN-connected room sensor microcontroller node. |
| **PNL** | Panel Module | Wall-panel logical agent and configuration role. |
| **Conflict Manager** | Independent supervisory processor | Maintains network-wide heartbeat registry and detects communication conflicts/failures independently of HCM. |

## Hardware and electrical terms

| Term | Meaning | Notes |
|---|---|---|
| **GPIO** | General-Purpose Input/Output | Processor digital I/O pins. |
| **I2C / I²C** | Inter-Integrated Circuit | Two-wire local peripheral bus used by relay, PWM, touch, and sensor devices. |
| **SPI** | Serial Peripheral Interface | Synchronous peripheral bus used for devices such as displays or CAN controllers. |
| **CAN** | Controller Area Network | Field bus used between SIM and RMC nodes. HomeControl uses 125000 bit/s. |
| **ADC** | Analog-to-Digital Converter | Converts analog voltage to digital measurement. |
| **DAC** | Digital-to-Analog Converter | Converts digital command to analog voltage; older LCM concepts used DAC modules. |
| **PWM** | Pulse-Width Modulation | Used by the active LCM PCA9685 0-10 V control architecture. |
| **DI** | Digital Input | Binary field input. |
| **DO** | Digital Output | Binary field output. |
| **AI** | Analog Input | Measured analog field signal. |
| **AO** | Analog Output | Commanded analog field signal such as 0-10 V. |
| **NO** | Normally Open | Relay contact open in its normal/deenergized state. |
| **NC** | Normally Closed | Relay contact closed in its normal/deenergized state. |
| **C / COM** | Common | Moving/common relay contact. |
| **PoE** | Power over Ethernet | Network cabling carrying both data and device power. |
| **HIL** | Hardware-in-the-Loop | Test mode where software drives or reads selected real hardware. |
| **0-10 V** | Analog lighting/control signal | Industry-standard low-voltage command range. |

## Networking and transport

| Term | Meaning | Notes |
|---|---|---|
| **IP** | Internet Protocol | Network addressing layer. |
| **TCP** | Transmission Control Protocol | Reliable stream transport used by module control and heartbeat HTTP. |
| **HTTP** | Hypertext Transfer Protocol | Used by HCM API and Unified Heartbeat V3 transport. |
| **API** | Application Programming Interface | Programmatic HCM/user/module interfaces. |
| **RPC** | Remote Procedure Call | Used for Shelly network dimmer operations. |
| **VLAN** | Virtual Local Area Network | Logical Ethernet network segmentation. Current HCM development/supervision uses VLAN 20. |
| **mTLS** | Mutual Transport Layer Security | TLS where both server and client authenticate with certificates. |
| **TLS** | Transport Layer Security | Encrypted/authenticated network transport. |
| **HMAC** | Hash-based Message Authentication Code | Shared-secret request authentication used by Heartbeat V3 and update requests. |
| **MAC address** | Media Access Control address | Stable physical-interface identifier used to derive HomeControl device IDs. |
| **NTP** | Network Time Protocol | Time synchronization. |
| **DNS** | Domain Name System | Hostname-to-address resolution. |

## Security and identity

| Term | Meaning | Notes |
|---|---|---|
| **PBKDF2** | Password-Based Key Derivation Function 2 | Used for HCM password hashing. |
| **scrypt** | Memory-hard password KDF | Used for touchscreen PIN hashing. |
| **WebAuthn** | Web Authentication | Standards-based passkey authentication; production assertion verification remains incomplete. |
| **Ed25519** | Edwards-curve digital signature algorithm | Used to verify signed update artifacts. |
| **SHA-256** | Secure Hash Algorithm 256-bit | Used for artifact hashing and token-related digests. |
| **UUID** | Universally Unique Identifier | Used for some internal identities/session concepts; not the preferred stable physical device ID. |
| **Device ID** | HomeControl stable device identifier | Normalized designated-interface MAC: lowercase, no separators. |
| **RP ID** | Relying Party Identifier | WebAuthn relying-party domain identifier. |
| **PKI** | Public Key Infrastructure | Certificate/key trust infrastructure for production mTLS. |

## Control and safety terms

| Term | Meaning | HomeControl usage |
|---|---|---|
| **Logical Device** | User-facing control object | Maps a meaningful name to one enabled hardware/module binding. |
| **Binding** | Logical-to-physical association | Connects logical device to module/channel and carries execution metadata. |
| **Execution Mode** | Binding control mode | `simulated` or `physical`. |
| **Output Intent** | Requested desired output state | Stored/prioritized request before safety arbitration. |
| **Safety Arbiter** | Command decision layer | Converts requested state into effective state under maintenance/fire/fault conditions. |
| **Maintenance Lockout** | Output inhibit | Highest-priority prevention of energization. Exists at system and logical-device scopes. |
| **System/LOT Lockout** | System life-safety maintenance inhibit | Used for wiring/testing maintenance while preserving fire detection. “LOT” is the project's maintenance lockout shorthand. |
| **Life Safety** | Fire/emergency control class | Overrides normal automation but remains below maintenance lockout for energization. |
| **Local Override** | Local/manual command class | Higher priority than normal user/rule commands. |
| **Safe Off** | Deenergized safety state | May be commanded even when normal energization authorization is unavailable. |
| **State Confidence** | Strength of state evidence | Indicates what kind of evidence supports the reported state. |
| **SIMULATED** | State-confidence label | State exists only in simulation/in-memory path. |
| **COMMANDED** | State-confidence label | Software command/state is known, but hardware output was not independently read. |
| **OUTPUT_LATCH_READBACK** | State-confidence label | Hardware output register/latch state was read back; does not prove electrical load response. |
| **DEVICE_REPORTED** | State-confidence label | Network device reported its own state, e.g. Shelly RPC response. |
| **PHYSICAL_FEEDBACK** | State-confidence label | Independent physical/electrical feedback confirms state. |
| **UNKNOWN** | State-confidence label | State cannot be established reliably. |

## Commissioning terms

| Term | Meaning |
|---|---|
| **UNVERIFIED** | Hardware/design has not been validated. |
| **DESIGN_APPROVED** | Design is accepted but not physically bench tested. |
| **BENCH_TESTING** | Explicit hardware-test phase; normal production commands still cannot energize outputs. |
| **BENCH_TESTED** | Hardware has passed defined bench validation but is not yet fully commissioned. |
| **COMMISSIONED** | Module is approved for normal physical operation when all enable gates are set. |
| **SIMULATED** | Profile/environment is intentionally nonphysical. |
| **Commissioning Gate** | Software check preventing physical writes unless module/profile requirements are satisfied. |

## Update and reliability terms

| Term | Meaning | Notes |
|---|---|---|
| **ACK** | Acknowledgement | Positive receipt/acceptance response. |
| **NACK** | Negative acknowledgement | Explicit rejection/failure response. |
| **CRC** | Cyclic Redundancy Check | Error-detection value used in firmware-transfer designs. |
| **Replay Protection** | Duplicate-request rejection | Prevents reuse of a previously accepted authenticated operation. |
| **Boot ID** | Per-process/start identifier | Heartbeat V3 uses it with sequence numbers to detect restart and replay. |
| **Heartbeat** | Periodic liveness/health report | Used both by TCP module sessions and the independent V3 supervisor. |
| **Watchdog** | Failure detector requiring periodic pulse | Heartbeat V3 can supervise named local processes. |
| **CI** | Continuous Integration | GitHub Actions automated test/compile/safety checks. |
| **SOT** | Source of Truth | Authoritative configuration or design reference. |

## Application and platform terms

| Term | Meaning |
|---|---|
| **HVAC** | Heating, Ventilation, and Air Conditioning |
| **TTS** | Text-to-Speech |
| **APNs** | Apple Push Notification service |
| **UI** | User Interface |
| **HMI** | Human-Machine Interface |
| **REST** | Representational State Transfer |
| **JSON** | JavaScript Object Notation |
| **SQL** | Structured Query Language |
| **PostgreSQL** | HCM's central relational database |
| **SQLite** | Embedded database used by Conflict heartbeat registry and updater replay state |
| **FastAPI** | Python web framework used by HCM |
| **SocketCAN** | Linux kernel CAN networking API |
| **gpiod** | Linux GPIO character-device userspace library/API |

## Terms intentionally distinguished

### Heartbeat vs control-session heartbeat

**Unified Heartbeat V3** is the independent supervision plane centered on Conflict Manager.

The **module TCP heartbeat** is part of the HCM control session and updates HCM state/liveness.

They are complementary, not interchangeable.

### Commanded off vs physically confirmed off

A successful OFF command or output-latch readback does not automatically prove that the downstream relay contact, controlled equipment, or electrical load is physically off.

Only independent feedback justifies the PHYSICAL_FEEDBACK confidence label.

### Commissioned module vs enabled output

A module being COMMISSIONED means its authoritative hardware inventory is approved as a unit. Actual physical energization still requires the module-level and section-level enable gates and a real I/O mode.

### Historical documentation

Older project documents contain superseded decisions, including VLAN 60 heartbeat plans, earlier fire polarity descriptions, eight-channel 0-10 V LCM designs, and simulated hardware assumptions. The current white papers and audited source should be used for present architecture.
