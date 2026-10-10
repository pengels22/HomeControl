# Jetson HCM verified deployment status — 2026-10-10

## Current operational status after Ethernet cutover — 2026-10-10

This addendum **supersedes the older Wi-Fi/routing claims below**. Jetson `eth0=192.168.20.27` via DHCP, metric 100; `wlan0=192.168.20.25` via DHCP, metric 300 saved (last observed active route metric 600 until reconnect). Conflict `192.168.20.26` USB Ethernet (metric 100) and `192.168.20.24` Wi-Fi (metric 300 configured). All interfaces remain on VLAN 20. On Jetson `hcm-routing.service` is now disabled, `hcm.service` no longer requires it, its `ExecStartPost` routing hook is disabled, and Mac-specific policy rule 1100 was removed. Wi-Fi-specific rule 1000/table 200 is retained. Do not resurrect rule 1100, the obsolete service dependency or the old static Jetson Ethernet address.

After a Jetson reboot, operator-reported verification showed `hcm`, `hcm-postgres`, `hcm-heartbeat`, `hcm-watchdog.timer` active; `hcm-test` running with published `192.168.20.27:8080`; HTTP GET dashboard returned 200; route to Conflict .26 was `eth0` sourced from .27. Unified Heartbeat V3 peer was online/healthy in the Conflict registry. No further crash-kill test after routing cleanup or Wi-Fi link-failure test is claimed. Follow [Phase 4 Codex contract](PHASE4_CODEX_IMPLEMENTATION_2026-10-10.md) for next-stage work.


## Watchdog validation update (2026-10-10, 11:45 EDT)

The watchdog was installed on Jetson with a timer every approximately 30 seconds. Following a deliberately killed HCM container, three consecutive failed direct-container HTTP checks triggered an HCM-only systemd restart, which succeeded and restored the Wi-Fi return route. The post-restart watchdog health check returned HEALTHY, the failure counter returned to zero, and PostgreSQL and Heartbeat V3 were active. See [watchdog runbook](JETSON_HCM_WATCHDOG_2026-10-10.md).

The original “continuous HCM health monitoring not implemented” statement below was correct at the earlier reboot milestone but is now **superseded for the HCM application**. The restart limit is coded but untested; delivery of alerts and DB/USB fault recovery are still pending.


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
