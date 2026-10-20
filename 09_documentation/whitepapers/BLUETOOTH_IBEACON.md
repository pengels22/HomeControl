# Native Bluetooth and iBeacon

HCM owns one native Bluetooth observation pipeline. The scanner normalizes BLE
advertisements into adapter, address, name, RSSI, timestamp, manufacturer data,
service UUID, service data, TX power, and connectability fields. A bounded,
expiring cache powers authenticated discovery at `/api/v1/bluetooth/discovery`;
unclaimed nearby devices are not written to the persistent HCM device registry.

The runtime target is Linux/BlueZ through an optional deferred `bleak` backend.
The scanner accepts an injected backend for tests and remains isolated when the
host adapter or dependency is unavailable. Adapter identity is retained in
each observation and configuration supports `auto`, `hci0`, `hci1`, or another
adapter name without hard-coding one interface.

iBeacon is a provider consumer of that scanner. It parses the Apple manufacturer
advertisement format (`0x004c`, type `0x0215`) and uses UUID + major + minor as
the stable identity, so rotating BLE addresses do not recreate a configured
beacon. Configured beacons expose presence, smoothed RSSI, and last-seen
entities. Entered and left events are emitted only on presence transitions;
RSSI updates do not flood the event bus. Presence expires after the configured
timeout and is not restored as present on HCM restart until a fresh packet is
observed.

RSSI is an approximate radio signal measure. No distance estimate or life-safety
behavior is derived from it. Bluetooth and iBeacon are advisory automation
inputs and never control HCM fire/life-safety, HVAC interlocks, commissioning,
heartbeat, or physical I/O.

CI uses fake advertisements and scanner backends. The implementation is
software-tested but has not been live-verified with a Linux adapter or physical
iBeacon.
