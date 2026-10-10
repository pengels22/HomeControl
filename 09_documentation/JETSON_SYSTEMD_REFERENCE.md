# Jetson systemd service inventory (verified 2026-10-10)

This is a configuration inventory, not an automated installer. See [the full deployment runbook](JETSON_HCM_DEPLOYMENT_2026-10-10.md).

| Unit | Responsibility | Boot status |
| --- | --- | --- |
| `hcm-heartbeat.service` | Independent host Python 3.6 Heartbeat V3 | enabled and active after reboot |
| `hcm-postgres.service` | Starts existing PostgreSQL Docker container after guarded USB mount | enabled and active after reboot |
| `hcm-routing.service` | Waits for Wi-Fi route table 200 | enabled and active after reboot |
| `hcm.service` | Checks PostgreSQL readiness, starts existing HCM Docker container | enabled and active after reboot |

HCM service installed at `/etc/systemd/system/hcm.service`: oneshot with RemainAfterExit, Requires/After Docker, hcm-postgres and hcm-routing; `ExecStartPre` checks `pg_isready`, `ExecStart` runs `docker start hcm-test`, `ExecStop` runs `docker stop -t 20 hcm-test`.

Drop-in `/etc/systemd/system/hcm.service.d/routing.conf` uses `ExecStartPost=/usr/local/sbin/hcm-update-routing` to discover current container address on `hcm-control` and apply policy rule pref 1100 to Wi-Fi table 200, currently only for the development Mac `192.168.1.241`.

The running unit is **not** the native virtual-environment sample at `07_servises/systemd/homecontrol-hcm.service`. These oneshot units supervise startup only, not continuous Docker application health.

Useful read-only checks:

```sh
systemctl is-active hcm-heartbeat hcm-postgres hcm-routing hcm
systemctl cat --no-pager hcm.service hcm-routing.service
findmnt /srv/hcm-data
sudo docker ps --filter name=hcm
ip -4 rule show
ip -4 route show table 200
```

Do not commit `/etc/hcm/hcm.env`, `/etc/hcm/postgres-password`, database contents or session tokens. Recheck DHCP addresses, routing marks, expected USB UUID and Docker network membership before reusing this deployment on another device.
