# HCM Staged Migration Plan

## Migration status update — 2026-10-10

The Jetson development HCM application and PostgreSQL were deployed on the **existing** VLAN 20 environment and survived a full reboot, with independent Heartbeat V3 on the existing network. This work did not migrate control modules to VLAN 40 or heartbeat to VLAN 60; stages below remain planning guidance unless specifically marked complete in source or [runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md). Do not apply proposed network/migration commands to the live host without a maintenance plan.


This plan records implementation impacts from the approved corrections. It does
not authorize live network changes, database migrations, or safety GPIO changes.

## Stage 0: Documentation And Templates

Status: complete for documentation/templates.

Actions:

- Mark VLAN 20 as current development/control.
- Mark VLAN 40 as future production/control with no approved subnet.
- Mark VLAN 60 as heartbeat/supervisory only.
- Mark VLAN 140 as not applicable.
- Document Conflict Manager heartbeat `192.168.60.2` on `eth0.60`, TCP 6004.
- Document normalized MAC device IDs.
- Document maintenance lockout as highest-priority output inhibit.

No live device migration is performed in this stage.

## Stage 1: Code Impact Inventory

Affected code paths:

- `07_servises/common/agent.py`: replace generated `module_uuid` identity with
  normalized MAC-derived `device_id`.
- `01_HCM/registry.py`: replace UUID registry assignment and lookups with
  `device_id`; assign new modules from configured control-network profiles
  instead of hardcoded VLAN 60 pools.
- `01_HCM/updater.py`: update module lookup and heartbeat-return checks from
  `module_uuid` to `device_id`.
- `01_HCM/devices.py`: ensure bindings and final output arbitration use device
  IDs internally while user commands remain logical-name based.
- `01_HCM/priority.py`: add or support final output state after safety
  arbitration, distinct from requested state.
- `01_HCM/safety.py`: verify fire response cannot energize any output inhibited
  by maintenance lockout.
- `00_Heartbeat/hcm_heartbeat.py`: normalize MAC IDs, validate 12-hex IDs, and
  use normalized IDs for allowlists and expected Conflict identity.
- `10_scripts/simulate_homecontrol.py`: keep simulated workflows isolated from
  live network changes while tests validate configured control-network behavior.
- `11_tests/test_registry.py`, `test_safety.py`, `test_priority.py`, and related
  tests: update assumptions and add lockout/fire arbitration coverage.

Affected database objects:

- `modules.module_uuid`
- `faults.module_uuid`
- `device_bindings.module_id`
- `rmc_firmware_updates.sim_module_id`
- `configuration_history.target_id`
- Any future event/audit records that identify physical devices

Affected configuration files:

- `06_config/01_HCM/hcm.yaml`
- `06_config/02_SIM/sim.yaml`
- `06_config/03_LCM/lcm.yaml`
- `06_config/04_RCM/rcm.yaml`
- `06_config/05_PNL/pnl.yaml`
- `00_Heartbeat/config-jetson.json`
- `00_Heartbeat/config-conflict.json`
- deployment/provisioning scripts under `06_config/` and `10_scripts/`

## Stage 2: Non-Destructive Identity Migration Design

Before applying any database migration:

- Inventory current module UUIDs, hostnames, IPs, physical devices, and raw MACs.
- Choose and document each device's identity interface.
- Produce a reversible migration script adding `device_id` alongside existing
  UUIDs.
- Backfill only reviewed device mappings.
- Add validation reports for orphaned bindings, faults, and update history.
- Keep writes dual-field until code and tests prove all paths use `device_id`.

Do not drop `module_uuid` in the first migration.

## Stage 3: Heartbeat V3 Normalization

Actions:

- Update V3 MAC normalization. Complete in code; requires deployment approval.
- Update Conflict allowlists to normalized IDs. Template updated; live config
  must be changed only during approved deployment.
- Keep current VLAN 20 heartbeat baseline until VLAN 60 is physically ready.
- Add tests for raw MAC to normalized device ID conversion. Complete.
- Add tests that malformed IDs are rejected and colon-form MACs normalize at
  input boundaries. Complete.

Do not bind Conflict to `192.168.60.2` until `eth0.60` is configured and tested.

## Stage 4: Control Network Migration Planning

Repository preparation now complete:

- HCM registry assignment reads the active control-network profile from
  `06_config/01_HCM/hcm.yaml`.
- The active template profile is VLAN 20 development/control.
- VLAN 40 exists as a disabled production profile and requires an explicit
  approved subnet and pools before assignment.
- VLAN 60 is rejected as a module-control profile and remains heartbeat-only.

Actions after VLAN 40 subnet approval:

- Enter the approved VLAN 40 subnet and module pools in the production profile.
- Enable assignment for the production profile only during an approved migration
  window.
- Update provisioning scripts/DHCP/firewall policy from the reviewed config.
- Keep VLAN 60 heartbeat-only.
- Produce rollback instructions.

Do not migrate existing VLAN 20 devices until an approved maintenance window.

## Stage 5: Safety Arbitration

Actions:

- Model requested output state separately from final output state.
- Ensure maintenance lockout inhibits energize commands before any hardware
  driver call.
- Ensure fire detection/logging/notification continues during lockout.
- Add tests for user, rules, local override, and fire paths while maintenance
  lockout is active.
- Document relay contact states and hardwired interlocks before hardware
  validation.

Do not modify safety GPIO drivers in this stage.

## Stage 5A: Phase 1 Deployment And Rollback

No production deployment has been performed.

### Jetson Deployment Plan

1. Confirm the current Jetson heartbeat service state:
   `systemctl status hcm-heartbeat.service`.
2. Back up `/etc/hcm-heartbeat/config.json`,
   `/usr/local/lib/hcm-heartbeat/hcm_heartbeat.py`, and any existing
   `/usr/local/lib/hcm-heartbeat/homecontrol_identity.py`.
3. Confirm the designated identity interface and raw MAC.
4. Install the updated heartbeat package from the repository checkout using
   `00_Heartbeat/install.sh`, or copy only the updated heartbeat files during a
   controlled maintenance window.
5. Keep current VLAN 20 addresses. Do not bind heartbeat to VLAN 60 yet.
6. Confirm `/status` shows normalized `device_id`.
7. Confirm the Jetson receives full Conflict responses and does not report
   `peer_offline` after startup grace.

Rollback:

1. Restore the backed-up `hcm_heartbeat.py`, `homecontrol_identity.py` if it
   existed, and `/etc/hcm-heartbeat/config.json`.
2. Run `systemctl daemon-reload`.
3. Restart `hcm-heartbeat.service`.
4. Confirm `/status` returns to the previous behavior.

### Conflict Manager Deployment Plan

1. Confirm the Conflict Manager service and current config on VLAN 20.
2. Back up `/etc/hcm-heartbeat/config.json`,
   `/usr/local/lib/hcm-heartbeat/hcm_heartbeat.py`, existing helper files, and
   `/var/lib/hcm-heartbeat/registry.sqlite3` if present.
3. Install the updated heartbeat package.
4. Keep `bind_address` on the current VLAN 20 baseline until `eth0.60` is
   approved and verified.
5. Update `allowed_device_ids` to normalized IDs only after the updated daemon
   is installed on all participating devices.
6. Confirm SQLite registry creation under `/var/lib/hcm-heartbeat/`.
7. Confirm registration persists across service restart and devices are marked
   last-known/offline until their next heartbeat.

Rollback:

1. Stop `hcm-heartbeat.service`.
2. Restore backed-up heartbeat files and config.
3. Optionally move the new SQLite registry aside rather than deleting it:
   `registry.sqlite3.phase1`.
4. Restart `hcm-heartbeat.service`.
5. Confirm old allowlist/device ID behavior is restored.

### HCM/PostgreSQL Deployment Plan

1. Do not run `08_database/001_device_identity_migration.sql` until a database
   backup and reviewed UUID-to-device-ID mapping exist.
2. When approved, run the migration in a maintenance window. It only adds
   nullable columns, constraints, and indexes.
3. Backfill `device_id` values from an operator-reviewed mapping, not from
   hostnames or IP addresses alone.
4. Keep `module_uuid` populated until validation proves all code paths use
   `device_id`.

Rollback:

1. Because the migration is additive, immediate rollback is to leave the new
   columns unused and restore pre-migration application code.
2. If required after backup verification, drop the added indexes/constraints and
   columns in a separate approved rollback migration.

## Stage 6: Production Behavior Change

Only after stages 1-5 are reviewed:

- Apply database migration in a backup-backed maintenance window.
- Roll module identities to normalized MAC IDs.
- Move production control to approved VLAN 40.
- Move heartbeat to VLAN 60 with Conflict at `192.168.60.2`.
- Verify PostgreSQL, HCM registry, Heartbeat V3, device configs, and fault
  history agree.
