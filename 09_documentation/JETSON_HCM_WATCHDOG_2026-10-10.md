# HCM watchdog: Jetson installation and recovery verification

## 2026-10-10 network and lifecycle update

The successful watchdog crash-injection test described below took place **before** the later Ethernet-first migration. The Jetson now runs Ethernet `192.168.20.27`, Wi-Fi `192.168.20.25`; HCM's old `hcm-routing.service` dependency and the `hcm-update-routing` post-start hook were disabled, and route rule 1100 was removed. The watchdog still targets HCM alone and must never change networking or restart PostgreSQL/Heartbeat V3. Later read-only checks confirmed `hcm-watchdog.timer` active, `hcm` and its Docker container running, and dashboard HTTP 200. **Crash recovery was not re-injected after the routing cleanup**; its earlier tested behavior and untested suppression/alert limits are accurately described in this document. See [live deployment addendum](JETSON_HCM_DEPLOYMENT_2026-10-10.md) and [current white papers](whitepapers/README.md).


**Verified on 2026-10-10** on the Jetson Xavier NX, Ubuntu 18.04/systemd 237/host Python 3.6. This is a record of the **running development deployment**, not validation of production fault tolerance.

## Versioned files

- [`10_scripts/hcm-watchdog.py`](../10_scripts/hcm-watchdog.py) — source of the installed `/usr/local/sbin/hcm-watchdog` Python 3.6 script
- [`07_servises/systemd/hcm-watchdog.service`](../07_servises/systemd/hcm-watchdog.service) — one-shot check service
- [`07_servises/systemd/hcm-watchdog.timer`](../07_servises/systemd/hcm-watchdog.timer) — boot/30-second recurrence

The unusual `07_servises` spelling is intentional and part of the repository layout. Source versions match the commands installed and tested during commissioning. **Git commits do not update the installed Jetson systemd units until an operator explicitly deploys them.**

## Monitor behavior

The watchdog reads the HCM container IP dynamically from Docker network `hcm-control` and requests `http://<container-ip>:8080/` directly (expects HTTP 200). This avoids the Jetson's known local timeout when curling its own published `192.168.20.27:8080` port, which works from the Mac but not locally. The loop uses `OnBootSec=60`, `OnUnitInactiveSec=30`, `AccuracySec=1`. It requires 3 consecutive failed checks, then attempts `systemctl restart hcm.service`, keeping no more than 3 recorded restart attempts in a sliding 900-second window. Counter/history JSON resides at `/var/lib/hcm-watchdog/state.json`. A nonblocking `flock` prevents overlapping watchdog executions. `--check-only` reports health without changing recovery counters or restarting HCM.

If `hcm.service` or `hcm-postgres.service` is inactive, recovery is suppressed. For planned maintenance use `sudo systemctl stop hcm.service`, not `docker stop hcm-test`; the latter looks like a crash to the monitor. Heartbeat V3 remains independent and is never explicitly restarted by this script. The watchdog relies on systemd's existing HCM dependencies and routing `ExecStartPost` hook; it neither rewrites the routing rule nor changes Docker restart policies.

At rest successful scheduled checks are silent in the journal apart from systemd start/finish messages. Check state file to see zero failures.

## Safe installation/reconciliation on the verified Jetson

Run on Jetson after review. No container restart is required simply to install these files.

```sh
cd ~/HomeControl
git pull --ff-only origin main

sudo install -m 0755 10_scripts/hcm-watchdog.py /usr/local/sbin/hcm-watchdog
sudo install -m 0644 07_servises/systemd/hcm-watchdog.service /etc/systemd/system/hcm-watchdog.service
sudo install -m 0644 07_servises/systemd/hcm-watchdog.timer /etc/systemd/system/hcm-watchdog.timer
sudo mkdir -p /var/lib/hcm-watchdog
sudo systemctl daemon-reload

# Test script before enabling scheduled automatic recovery
python3 -m py_compile /usr/local/sbin/hcm-watchdog
sudo /usr/local/sbin/hcm-watchdog --check-only
sudo systemctl enable --now hcm-watchdog.timer
systemctl status hcm-watchdog.timer --no-pager
systemctl list-timers --all --no-pager | grep hcm-watchdog
sudo cat /var/lib/hcm-watchdog/state.json
```

The above should match existing configuration; check `git diff` and live installed files before making future changes. There is **no need to rerun these steps immediately** on the host already installed and tested.

If a full planned HCM maintenance stop is required, use `sudo systemctl stop hcm.service` and independently observe whether the watchdog logs `recovery suppressed`. Do not stop Heartbeat V3. Do not erase the state file during ordinary production operation.

## Operator-observed crash recovery on 2026-10-10

- `sudo /usr/local/sbin/hcm-watchdog --check-only` returned `HCM WATCHDOG: Health check: HEALTHY`.
- First timer check after activation and subsequent checks successfully scheduled at 30-second intervals; state showed `{"failures": 0, "restarts": []}`.
- The operator issued `sudo docker kill hcm-test` for a single controlled test; Docker restart policy was `no`, so the container remained down until watchdog intervention.
- Journal: **11:44:11** first failure (1/3), **11:44:41** second (2/3), **11:45:12** third (3/3) and HCM-only restart attempted.
- `hcm.service` completed stop/start, started `hcm-test` at approximately **11:45:13 EDT**, and reran `hcm-update-routing` at **11:45:14**, installing policy route from `172.19.0.2` to `192.168.1.241` via table 200.
- Watchdog recorded one restart: `{"failures": 0, "restarts": [1791647112]}`; subsequent `--check-only` returned `HEALTHY`, and the 30-second timer was still scheduled.
- `hcm-postgres.service` and `hcm-heartbeat.service` remained **active** after recovery. This verifies service state, **not** packet-level heartbeat continuity or database transaction continuity throughout the intentional test.

## Known limits and follow-up

- The **3 attempts / 15 minutes** suppression path is implemented but has **not** been tested. It logs an `ALERT` in the journal; alert delivery to the phone/email is not enabled. Once the limit is reached, it does not prevent further failure logging.
- The watchdog uses the web root returning HTTP 200 as a liveness check, not a full database query, hardware/safety probe or user-authenticated transaction.
- A slow/unreachable Docker bridge can cause a false negative. The `hcm.service` unit is `oneshot` / `RemainAfterExit=yes`, and a simple administrative `docker stop` appears indistinguishable from a crash until the systemd unit is stopped. Concurrent systemd maintenance can still race the monitor despite final active-state rechecks.
- This script can restart HCM while the independent Heartbeat V3 host daemon remains active, but **it is not itself a safety monitor** and should not be relied on for emergency relay control.
- Unit/service `TimeoutStartSec=150` is set; script calls systemd restart with timeout 120. This has been proven for one normal controlled failure only, not hung Docker daemon or long blocked disk I/O.
- No phone/email notification integration was requested for this stage. Leave notifications deferred until explicitly wanted.
