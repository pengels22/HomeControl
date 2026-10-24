# Pass 9.1 — SIM reference audit

| Reference | Classification | Reason retained or changed |
|---|---|---|
| `09_database/schema.sql:sim_module_id` | Historical compatibility | Existing RMC update records must remain readable. |
| `09_database/026_legacy_module_deprecations.sql` | Historical migration | Applied migration history is immutable. |
| `02_HCM/legacy_module_status.py` | Historical status | Reports legacy SIM/RMC retirement without registering or provisioning them. |
| `02_HCM/metadata_api.py`, `02_HCM/entities.py` | Historical projection | Compatibility metadata and source labels remain readable; no SIM device path is created. |
| `08_servises/common/rmc_firmware.py`, `07_config/06_RMC/*` | Historical protocol | CAN frame/state names describe the existing RMC update protocol; physical transport remains gated. |
| White papers and Pass 2 records | Historical documentation | Updated where active architecture was described; retained terminology is explicitly marked historical. |
| Generic `simulation` / `SIMULATED` strings | Unrelated execution mode | These describe safe software simulation and are not SIM module identifiers. |

No active import, service manifest, installer, inventory option, API route, or UI
role selector depends on `02_SIM` or offers SIM provisioning.
