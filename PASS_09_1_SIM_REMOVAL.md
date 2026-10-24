# Pass 9.1 — SIM removal and dependency cleanup

## Removed

- Deleted the tracked `02_SIM/` implementation and `07_config/02_SIM/` package.
- Removed SIM from module registration, role switching, deployment manifests,
  inventory selection, global configuration loading, storage initialization,
  update installer allowlists, provisioning, and touchscreen role controls.
- Removed SIM dashboard/name-edit APIs, the SIM-backed RMC firmware update API,
  the obsolete local SIM simulator, preview, and SIM-only tests.

## Retained

- PostgreSQL migration history, `sim_module_id`, historical SIM module rows,
  audit data, and RMC CAN protocol names remain readable.
- Generic simulation safety behavior remains; “simulation” is an execution mode,
  not a SIM module registration path.
- RCM, LCM, HVAC, safety arbitration, Heartbeat V3, and PNL code remain active.

## Replacement and deployment gate

PNL is the active room-panel telemetry and local-alias architecture. Existing
historical SIM sensor records were not silently remapped to PNL because that
requires deployed-device identity and binding information. This pass changes
repository behavior only; Jetson was not modified or redeployed.
