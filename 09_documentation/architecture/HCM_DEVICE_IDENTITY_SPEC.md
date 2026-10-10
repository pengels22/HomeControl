# HCM Device Identity Spec

## Approved Identifier

The authoritative device identifier is the MAC address of a designated physical
network interface.

Normalization:

1. Convert to lowercase.
2. Remove colons.

Example:

- Raw MAC: `48:b0:2d:87:db:16`
- Device ID: `48b02d87db16`

The normalized device ID is exactly 12 hexadecimal characters. It is not a
standard 128-bit UUID and must not be stored in UUID-typed columns.

## Scope

The normalized device ID replaces separately generated module UUIDs throughout:

- PostgreSQL module registration.
- HCM module registry.
- Heartbeat V3 device and allowed-device identity.
- Device commissioning.
- Device configuration.
- Fault history.
- Firmware update history.
- Configuration history.
- Automation-internal device relationships where a physical device relationship
  is required.

Human-readable hostnames remain separate. Logical device names remain separate
and continue to be the automation/user-facing control surface.

## Interface Selection

Each processor must document its designated physical identity interface. The
identity interface does not need to carry the packet being sent.

Examples:

- Jetson development HCM may use Ethernet MAC as identity even when heartbeat
  traffic currently leaves over Wi-Fi.
- Conflict Manager currently uses `wlan0` for the development baseline and will
  use `eth0` when the Ethernet adapter and `eth0.60` heartbeat interface are in
  service.

Virtual, transient, USB gadget, or Wi-Fi randomized MACs must not be selected as
authoritative identity interfaces.

## Current Repository Gaps

Phase 1 compatibility keeps legacy identifiers while adding normalized
`device_id` support. Remaining legacy paths still include:

- Existing identity files may contain `module_uuid` values generated from
  module type and machine ID.
- PostgreSQL keeps `modules.module_uuid UUID`.
- PostgreSQL keeps `faults.module_uuid UUID`.
- HCM registry accepts legacy `module_uuid` during transition.

These are migration compatibility surfaces. Do not perform a destructive
migration or remove them until validation passes.

## Database Migration Requirements

Migration must preserve existing relationships, assignments, and history.

Affected tables:

- `modules`
- `device_bindings`
- `faults`
- `firmware_releases`
- `rmc_firmware_updates`
- `configuration_history`
- Any future audit/event tables referencing modules or physical devices

Required migration pattern:

1. Add nullable `device_id TEXT` columns with a 12-hex check constraint where
   needed.
2. Add `identity_interface TEXT` where the source interface must be recorded.
3. Backfill reviewed mappings from existing module UUIDs to normalized MAC IDs.
4. Add unique indexes for populated `device_id` values.
5. Update code to write both legacy and new identifiers during transition.
6. Update reads to prefer `device_id` but tolerate legacy rows.
7. Migrate foreign references and history with validation queries.
8. Only after verification, retire legacy UUID fields in a separate approved
   migration.

No migration step should delete rows, overwrite history, or infer a MAC from an
unverified hostname/IP alone.

## Recommissioning

If the designated physical interface changes:

1. Put the device in maintenance/commissioning workflow.
2. Record the old device ID and new raw MAC.
3. Verify the hardware replacement or interface change physically.
4. Normalize the new MAC.
5. Create an explicit identity replacement record linking old and new IDs.
6. Move hostname, logical bindings, configuration assignment, and active device
   role only after operator approval.
7. Preserve old faults, events, and configuration history under the old ID while
   linking them to the replacement event.
8. Restart Heartbeat V3 and module services with the updated identity
   interface.
9. Confirm HCM registry, PostgreSQL, and Conflict Manager agree on the new ID.

Do not silently reuse an old device ID for different hardware.
