# Production Web UI Rebuild Notes

Status: development branch implementation notes. This is not a deployment
record and does not authorize Jetson, Conflict, LAB1, service, database, VLAN or
physical-output changes.

## Implemented Scope

- Authenticated dark-theme HCM web shell with Dashboard, Devices, Service,
  Settings and Users navigation.
- Dashboard now acts as a compact HCM system-health overview. It uses
  authenticated HCM APIs for backend health, HVAC state, module registry and
  logical-device maintenance lockouts, and displays `Unavailable` for
  Conflict heartbeat supervisor, fire/life-safety and active-fault details
  unless those values are explicitly reported by HCM health data.
- Registered-device list is loaded from HCM `/api/v1/modules`; offline devices
  remain visible.
- Device detail pages resolve through HCM by selected logical hostname or device
  identifier. The browser does not route to module IP addresses or physical
  control endpoints.
- LAB1 and other devices select their interface from HCM state/role information
  before falling back to registered module type. `UNASSIGNED` remains an
  operational role, not a `modules.module_type` value.
- RCM detail page renders 32 relay channels from existing device bindings and
  logical devices. ON/OFF uses the existing logical command endpoint. Maintenance
  lockout uses the existing safety lockout endpoint.
- RCM channel display names are stored in existing logical-device metadata for
  bound channels. This preserves logical device identity and avoids introducing a
  parallel production state store.
- LCM, SIM and UNASSIGNED pages show real identity/status information only.
- Pairing-key administration, pairing-code screens and iOS companion-app flows
  are removed from the active production web UI.
- LCM pages render the corrected 22-output physical inventory in two frontend
  sections only: eight Relay outputs in Lights, and fourteen dimmers in Dimmers
  (`10-1` through `10-10` for 0-10 V, `HV-1` through `HV-4` for 110 V). Output
  commands use HCM logical-device routing; settings update logical-device
  metadata and maintenance lockout continues through the existing safety lockout
  endpoint. Unbound physical channels are visible but disabled.
- SIM pages render CAN loop status, room-grouped RMC sensor clusters, editable
  bound RMC names, and ten physical analog inputs (`AI-1` through `AI-10`).
  RMC and analog names are persisted through HCM logical-device metadata only
  when a valid binding already exists; unbound inputs/nodes remain visible but
  non-configurable.

## Standalone Development Preview

Run the local UI preview on a Mac:

```sh
.venv/bin/python 11_scripts/preview_homecontrol_ui.py
```

Open `http://127.0.0.1:8081`. The preview binds to `127.0.0.1`, serves the
actual assets from `01_HCM/www/`, and implements only preview fixtures for the
API endpoints used by the frontend. It does not require PostgreSQL or Docker and
does not contact production HCM, Jetson, Conflict, LAB1 or physical modules.

Preview fixtures:

| Device | Role | Status |
| --- | --- | --- |
| LAB1 | UNASSIGNED | Online |
| RCM1 | RCM | Online |
| RCM2 | RCM | Online |
| LCM1 | LCM | Online |
| LCM2 | LCM | Online |
| SIM1 | SIM | Online |
| SIM2 | SIM | Online |
| RCM3 | RCM | Offline |

The preview RCM pages simulate ON/OFF, maintenance lockout and channel-name
edits through in-memory preview API state. The preview LCM pages simulate light
switching, dimmer brightness, maximum-intensity clamping, fade-setting metadata,
channel settings, emergency-lighting classification and maintenance lockout.
Maintenance lockout forces a channel OFF, rejects energizing commands while
locked, and leaves the channel OFF when cleared. This simulation is for visual
review and page-by-page frontend development only.

The preview SIM pages simulate independent CAN loop states, multiple rooms,
multiple RMCs in one room, editable RMC names, active/faulted/stale/missing RMC
telemetry, and all ten analog input rows. These preview fixtures are isolated
from production HCM, PostgreSQL, Jetson, Conflict, LAB1 and physical modules.

LCM preview and HCM UI enumeration use this physical mapping:

| Position | Channel | Type |
| --- | --- | --- |
| 1-8 | `A1`-`A8` | Relay |
| 9-18 | `10-1`-`10-10` | 0-10 V |
| 19-22 | `HV-1`-`HV-4` | 110 V |

The checked-in RMC/SIM protocol supports these RMC fields: CAN node address,
CAN loop/interface when recorded by SIM, last seen/heartbeat timing,
temperature in C/F, relative humidity percent, lux, ENS160 AQI, RCWL-0516
presence, sensor health flags, fault masks/names, status flags, uptime,
firmware version and hardware revision when reported during update/application
flows. The web UI shows `Unknown` or `Stale` when these values are missing or
stale; it does not infer health from saved configuration alone.

## Explicitly Not Complete

- HCM-hosted CSV files such as `RCM_2.csv` are not implemented by this UI
  change.
- Mirroring HCM configuration to local module CSV files is not implemented or
  claimed.
- Reconnection reconciliation that retrieves module-local state before
  overwriting HCM configuration is not implemented or claimed.
- Offline maintenance-lock reconciliation from module-local storage is not
  implemented or claimed.
- Hardware replacement/reassignment remains manual and unimplemented. The UI is
  shaped to preserve logical identities separately from MAC-derived device IDs,
  but it does not perform reassignment.
- Detailed SIM controls are intentionally deferred. LCM production backend
  integration beyond existing logical command routing and metadata writes is
  intentionally deferred.
- Dashboard thermostat controls use the existing production HVAC endpoints:
  `GET /api/v1/hvac`, `PUT /api/v1/hvac/mode`, and
  `PUT /api/v1/hvac/setpoint`. The current production backend supports
  `OFF`, `HEAT`, `COOL` and `FAN`. Heat/Cool is represented in the standalone
  preview to validate the modal and five-degree band calculation, but the
  production UI does not submit Heat/Cool while the backend model lacks that
  mode.
- Future production Heat/Cool support still requires backend thermostat
  arbitration that enforces mutual exclusion, minimum on/off timers, compressor
  short-cycle protection, safe transitions, verified equipment/temperature
  feedback, and hysteresis separate from the displayed five-degree target band.
- Settings uses `GET /api/v1/settings/network` for read-only HCM/network
  status. Registered module addresses come from the HCM module registry. HCM
  host interfaces are shown only when a structured host-side network status
  file is explicitly configured through `HCM_HOST_NETWORK_STATUS_FILE`; the UI
  otherwise displays host interfaces as unavailable rather than mislabeling the
  container network namespace as the controller host.
- Users uses the existing HCM users table, PBKDF2 password hashing and
  authenticated sessions. Admins can list users, create new users, change roles
  and reset passwords through `/api/v1/auth/users` endpoints. Password resets
  and role changes revoke existing sessions for that account. The backend
  rejects demotion of the final active ADMIN.
- The SIM UI enumerates ten requested physical analog input rows. The checked-in
  SIM firmware/config still defines eight Hexa AIO analog inputs (`A1`-`A8`) in
  `07_config/02_SIM/sim.yaml`; `AI-9` and `AI-10` have no verified module-local
  telemetry/config source yet and remain `Unknown` unless HCM state later
  reports them.
- Production SIM room/RMC assignment depends on existing HCM logical devices,
  rooms and bindings. There is no separate RMC registry table, CSV sync,
  local-module persistence, or offline reconciliation implemented by this UI
  work.
- The current LCM hardware profile defines 8 relay outputs (A1-A8), ten 0-10 V outputs (10-1 through 10-10), and four high-voltage dimmer channels (HV-1 through HV-4). The UI must use those current identifier families and must not revive the retired 12-relay / 8-dimmer layout.
- Production LCM hardware fade execution, live in-progress fade telemetry,
  module-local persistence of dimmer settings, CSV generation such as
  `LCM_1.csv`, authenticated TCP mirroring, and offline reconciliation are not
  implemented or claimed by the UI preview.

## Safety Notes

No production deployment, Jetson restart, Conflict change, PostgreSQL migration,
LAB1 role change, physical-output enablement, VLAN migration or service edit is
part of this work.
