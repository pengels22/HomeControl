# HomeControl Unified Deployment Framework

`10_Common` contains the shared manifest validation, inventory, release pinning,
and deployment-planning logic used by the Mac CLI and future HCM commissioning
integration.

Current safety posture:

- Deployment plans are source-tree only and use mocked remote execution.
- A full 40-character Git SHA is required when an operator supplies a release.
- Device manifests are validated before any target package is selected.
- Live secrets, certificates, databases, networking, watchdogs, and service state
  are device-specific state and are never stored here.
- Firmware targets such as `06_RMC` are modeled separately and are never flashed
  by the generic Linux deployment path.

The shell entry points are lightweight wrappers. They are intentionally safe for
local validation and must not be treated as live deployment approval.
