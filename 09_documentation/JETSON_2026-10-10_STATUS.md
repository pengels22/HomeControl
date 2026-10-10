# Jetson HCM verified deployment status — 2026-10-10

See [full deployment runbook](JETSON_HCM_DEPLOYMENT_2026-10-10.md).

## Validated

- Jetson Xavier NX Ubuntu 18.04.6 host, native Python 3.6 for independent Unified Heartbeat V3.
- HCM Docker image running Python 3.13, PostgreSQL 16 in a private Docker network, database data on mounted USB.
- HCM dashboard accessible from development Mac after boot; authentication and API requests worked.
- Enabled systemd services `hcm`, `hcm-routing`, `hcm-postgres`, `hcm-heartbeat` all automatically active after a full host reboot on 2026-10-10.
- Policy routing rule preference 1100 dynamically detects HCM control container IP and uses Wi-Fi routing table 200 for returns to development Mac 192.168.1.241.

## Outstanding

- Continuous application/database health monitoring and automatic restart/alerts.
- Rotate test admin credentials; deploy TLS and restricted access.
- Test backups, restore and USB power-loss behavior before production.
- Replace the single-Mac IP return-routing constraint with authorized client routing and document reproducible service installation.
- Validate all GPIO, hardwired fire and life-safety paths separately; current HCM GPIO is simulated.
- VLAN 40 production control and VLAN 60 heartbeat migration are not yet deployed.

## Superseded statements in older documents

Older readmes that describe PostgreSQL, Jetson systemd deployment, or authentication as entirely unverified predate the above dated validation. The legacy root docker-compose file and `07_servises/systemd/homecontrol-hcm.service` are development/alternative examples, not live Jetson service configurations. Older Heartbeat documentation may describe previous registry persistence; check the current architecture specification and live installed release before assuming historic claims apply.
