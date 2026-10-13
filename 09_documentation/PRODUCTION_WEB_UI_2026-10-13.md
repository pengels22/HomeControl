# Production Web UI Rebuild Notes

Status: development branch implementation notes. This is not a deployment
record and does not authorize Jetson, Conflict, LAB1, service, database, VLAN or
physical-output changes.

## Implemented Scope

- Authenticated dark-theme HCM web shell with Dashboard, Devices, Service,
  Settings and Users navigation.
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
- LCM pages render bound channel data in two frontend sections only: Lights and
  Dimmers. Output commands use HCM logical-device routing; settings update
  logical-device metadata and maintenance lockout continues through the existing
  safety lockout endpoint.

## Standalone Development Preview

Run the local UI preview on a Mac:

```sh
.venv/bin/python 10_scripts/preview_homecontrol_ui.py
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
| RCM3 | RCM | Offline |

The preview RCM pages simulate ON/OFF, maintenance lockout and channel-name
edits through in-memory preview API state. The preview LCM pages simulate light
switching, dimmer brightness, maximum-intensity clamping, fade-setting metadata,
channel settings, emergency-lighting classification and maintenance lockout.
Maintenance lockout forces a channel OFF, rejects energizing commands while
locked, and leaves the channel OFF when cleared. This simulation is for visual
review and page-by-page frontend development only.

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
- Production LCM hardware fade execution, live in-progress fade telemetry,
  module-local persistence of dimmer settings, CSV generation such as
  `LCM_1.csv`, authenticated TCP mirroring, and offline reconciliation are not
  implemented or claimed by the UI preview.

## Safety Notes

No production deployment, Jetson restart, Conflict change, PostgreSQL migration,
LAB1 role change, physical-output enablement, VLAN migration or service edit is
part of this work.
