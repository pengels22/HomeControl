# HomeControl Network, Communications, and Supervision White Paper

**Audited software baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`

## Purpose

This paper defines the current HomeControl network topology and communication planes. It supersedes older project documents that describe VLAN 60 as the active heartbeat network.

## Current network baseline

The current HomeControl development/control and heartbeat environment uses VLAN 20.

Known addresses:

- HCM/Jetson Ethernet: `192.168.20.27`
- HCM/Jetson Wi-Fi: `192.168.20.25`
- Conflict Manager Ethernet: `192.168.20.26`
- Conflict Manager Wi-Fi: `192.168.20.24`
- LAB1: `192.168.20.36`

Heartbeat/supervision also uses VLAN 20.

## Future network planning

VLAN 40 remains reserved as a future production HCM control network.

Its final subnet and allocation pools are not approved and must not be invented.

## Superseded VLAN 60 design

VLAN 60 is not part of the current approved architecture.

Historical references to:

- Conflict Manager `192.168.60.2`;
- `eth0.60`;
- heartbeat migration to VLAN 60;

are superseded.

## Communication planes

HomeControl intentionally separates several traffic classes.

### ACM supervision and HCM integration

ACM has two distinct integration paths. ACM initiates TCP sessions to keypad
listeners; keypads send a heartbeat every 30 seconds and become offline at
approximately 90 seconds, with their eight remote inputs marked FAULT. A
reconnect validates keypad identity and requires a complete eight-input
snapshot before clearing FAULT. ACM-to-keypad supervision is separate from
ACM-to-HCM status/time exchange and from Unified Heartbeat V3/Conflict
supervision.

ACM sends HCM compact `ACM_STATUS` containing only:

- `device_id`;
- `hostname`;
- `sequence`;
- `state`;
- `countdown`;
- `trouble`.

It does not send sensor maps, Areas, credentials, relay topology, or keypad
topology. Time follows `HCM → ACM → keypad`; ACM has no public Internet NTP
primary. HCM acknowledgements or HCM heartbeat status do not gate ACM alarm
authority.

### HCM user/API plane

Users, browser clients, future companion apps, and panels communicate with HCM through its API.

Current HCM API port:

- TCP 8080

Normal applications do not directly control field modules.

### HCM module-control plane

Linux modules maintain persistent TCP sessions to HCM.

Current control port:

- TCP 6501

Protocol:

- length-prefixed JSON frames;
- identify;
- assignment/config;
- command;
- command acknowledgement;
- state;
- fault;
- log event;
- heartbeat;
- heartbeat acknowledgement.

The transport supports TLS/mTLS, though development YAML defaults currently leave TLS disabled.

Production deployment must use certificate-backed module identity.

### Unified Heartbeat V3 supervision plane

Network-wide supervision is handled independently of HCM's application control session.

Current heartbeat port:

- TCP 6004

Transport:

- HTTP request/response;
- HMAC-SHA256 authentication in secured configuration;
- stable MAC-derived device ID;
- boot ID;
- sequence;
- timestamp;
- health and status payloads.

### Local heartbeat control

Local applications publish faults, status, and watchdog pulses to the local heartbeat daemon through:

`/run/hcm-heartbeat/control.sock`

This lets the independent heartbeat service report HCM/module application health without making the application itself the network supervisor.

### SIM/RMC CAN plane

RMC field communication uses Classical CAN.

Authoritative bitrate:

- 125000 bit/s

Configured SIM interfaces:

- can0
- can1
- can2

The SIM Linux SocketCAN implementation can receive real CAN frames.

## Device identity

The stable HomeControl device ID is derived from a designated physical interface MAC address.

Format:

- lowercase;
- no colons;
- exactly 12 hexadecimal characters.

Example:

`48:b0:2d:87:db:16` -> `48b02d87db16`

The identity interface can differ from the interface carrying heartbeat traffic.

## Conflict Manager

The Conflict Manager is an independent supervisory authority.

It maintains a SQLite registry containing:

- authorized devices;
- last hostname;
- advertised and observed IP;
- boot ID;
- last sequence;
- last health/status;
- online/offline state;
- communication-loss history;
- replay and duplicate-ID events.

It does not depend on HCM PostgreSQL to determine whether a device is alive.

## Heartbeat replay protection

For a device with the same boot ID, Conflict rejects a sequence number less than or equal to the last accepted sequence.

Conflict also checks timestamp skew and HMAC.

A new boot ID is treated as a restart event.

## Acknowledgement validation

The sending device validates the Conflict response including:

- protocol/version;
- `reply_to` sequence;
- `reply_boot_id`;
- expected Conflict hostname;
- expected Conflict device ID;
- HMAC signature;
- health/status shape.

## Duplicate-device detection

Conflict compares stable device ID, boot ID, source address, and recent reachability.

A currently reachable device ID appearing from a different source/boot context can be flagged as a duplicate-device conflict.

## HCM module session heartbeat vs Unified Heartbeat V3

These are deliberately separate.

### Module session heartbeat

Purpose:

- TCP control-session liveness;
- module state update;
- HCM registry online state.

When this HCM session is lost, modules retain their last output states;
RCM local overrides remain available. A reconnect sends the current module
state immediately, and HCM defers new energizing commands until it records that
state. Explicit deenergizing safety commands remain available. The reported state remains commanded/device state, not proof of
physical load state.

### Unified Heartbeat V3

Purpose:

- independent processor supervision;
- system/service/watchdog health;
- communication-loss detection;
- durable supervisory history.

Neither should be treated as a replacement for the other.

## CAN transport status

SIM has a real Linux SocketCAN receive path.

Transport lifecycle includes:

- explicit active transport ownership;
- task cancellation;
- socket close;
- cleanup of partial startup failures.

Real interface setup remains an explicit deployment prerequisite; the application does not silently invent interface names or bitrates.

## Security boundaries

Heartbeat identity fields such as MAC, hostname, and IP are operational identifiers, not cryptographic identity on their own.

Current secured heartbeat uses HMAC.

Module-control production transport is intended to use mTLS.

Neither plane should be exposed directly to the public Internet.

## Current limitations

Not yet fully commissioned:

- production mTLS deployment;
- physical CAN bus validation on installed SIM/RMC hardware;
- full HIL supervision failure testing;
- final VLAN 40 production migration.

The current VLAN 20 development deployment is the authoritative active topology until a separate approved migration occurs.
