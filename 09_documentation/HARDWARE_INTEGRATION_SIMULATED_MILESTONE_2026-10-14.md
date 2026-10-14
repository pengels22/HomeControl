# Hardware Integration Simulated Milestone - 2026-10-14

This branch adds shared simulated infrastructure for HomeControl module health,
configuration persistence, structured event logging, and Git-backed HCM storage.
No production hardware, firmware, Conflict service, LAB1 role, VLAN, database schema,
or deployed Jetson service was changed.

## Implemented in Simulation

- Shared I2C component inventory for the verified relay cards and MCP expanders:
  `0x20`, `0x21`, `0x26`, and `0x27`.
- RCM physical relay mapping for A1-D8 across Relay Card 1 and Relay Card 2.
- LCM runtime inventory corrected to 8 relays, 10 analog 0-10V dimmers, and 4 HV dimmers.
- Commanded-state reporting explicitly marks RCM relay state as commanded-only with no contact feedback.
- Common module status, health, and read-only emergency configuration endpoints using HCM bearer-token authentication.
- Default module emergency web port changed to `6010`.
- Local JSONL structured event logger with duplicate suppression after the third repeated non-safety event.
- Offline event queue with idempotent enqueue and delivery removal.
- Local configuration store, including strict RCM CSV schema: `Channel ID,Name,on,Lockout`.
- HCM `/var/lib/homecontrol` storage layout helper with local Git initialization.
- ADMIN-only HCM Git settings endpoints and Settings UI controls with PAT redaction.

## Not Implemented or Not Physically Verified

- TCP synchronization of HCM-hosted CSV files to physical modules is not implemented or tested.
- Offline maintenance-lock reconciliation before resynchronization is not implemented.
- Real LCM analog PWM hardware is intentionally left as `TBD`; the model, address, frequency,
  and polarity remain unverified.
- Real Shelly Pro dimmer control is represented only as disabled network I/O health metadata.
  No RPC contract or physical command path was introduced.
- RCM relay output feedback is not available; state remains commanded-only.
- Emergency module configuration pages are read-only in this milestone. Mutating operations
  still require verified HCM workflows.
- GitHub remote synchronization is configurable but no automatic push/pull workflow is enabled here.

## Safety Notes

- Real hardware adapters remain disabled by default.
- Browser and preview paths continue to route commands through authenticated HCM APIs.
- No direct browser-to-module hardware control path was added.
- Maintenance, fire/life-safety, and existing safety arbitration behavior were not weakened.
