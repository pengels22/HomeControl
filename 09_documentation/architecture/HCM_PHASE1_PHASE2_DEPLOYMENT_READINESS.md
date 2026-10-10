# HCM Phase 1/2 Deployment Readiness Review

## Deployment outcome addendum — 2026-10-10

The original gate below predates deployment. The Jetson host Python 3.6 Unified Heartbeat V3 daemon and the Docker Python 3.13 HCM application have since been run on actual Jetson hardware. An operator-observed full reboot recovered both services, PostgreSQL and routing and the web dashboard loaded. See [Jetson runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md). This clears the specific *unverified Jetson runtime* concern stated below, but does **not** indicate production approval or completion of pending VLAN 60, life-safety GPIO, database backup, TLS or crash recovery work. The historic deployment/rollback procedure below remains a dated plan, not a command to redeploy the existing installation.


This review covers the repository implementation only. Do not deploy or change
live hardware from this document without explicit approval.

## Readiness Result

Deployment is not yet recommended until one blocker is cleared:

- Python 3.6 runtime execution has not been verified in this development
  environment because no `python3.6` interpreter or Jetson image is available.
  Syntax was checked for the Python 3.6-targeted heartbeat files, but runtime
  verification must be performed on a Jetson-equivalent Python 3.6 host before
  production rollout.

All other reviewed items are ready for staged operator validation.

## Mixed-Version Interoperability

Safe order:

1. Update Conflict Manager first.
2. Verify it still accepts the currently deployed Jetson heartbeat.
3. Update Jetson second.

Reason:

- Updated Conflict normalizes incoming legacy colon-form MAC IDs at the HTTP
  protocol boundary and stores the canonical 12-character `device_id`.
- Updated Jetson sends normalized IDs. A previously installed Conflict daemon
  that still expects colon-form MACs may reject normalized IDs.

The reverse order, Jetson before Conflict, is therefore not recommended.

Rollback order if both hosts were updated:

1. Roll Jetson back first.
2. Confirm old colon-form heartbeats are accepted.
3. Roll Conflict back second only if required.

## Identity And Registry Checks

- Incoming heartbeat `device_id` values are normalized before allowlist checks,
  in-memory peer storage, and SQLite persistence.
- Existing `allowed_device_ids` may contain colon-form or normalized MACs; the
  updated daemon normalizes the allowlist on startup.
- Colon-form and normalized reports for the same physical interface collapse to
  one SQLite `devices.device_id` row.
- Duplicate currently reachable IDs from a different source IP and boot ID are
  rejected and logged as `duplicate_device_id`.

## Network Preservation

The staged deployment keeps:

- Conflict Manager on `192.168.20.26`.
- Jetson on `192.168.20.27`.
- Heartbeat TCP port `6004`.
- VLAN 60 reserved but not activated for this deployment.

Do not bind Conflict to `192.168.60.2` until `eth0.60` is configured and a
separate VLAN 60 maintenance window is approved.

## Conflict Manager Commands

Run these commands on `conflict` (`192.168.20.26`) only during an approved
maintenance window.

### Backup

```sh
TS="$(date -u +%Y%m%dT%H%M%SZ)"
sudo mkdir -p "/root/hcm-heartbeat-backup-$TS"
sudo cp -a /etc/hcm-heartbeat/config.json "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo cp -a /etc/systemd/system/hcm-heartbeat.service "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo cp -a /usr/local/lib/hcm-heartbeat "/root/hcm-heartbeat-backup-$TS/lib" 2>/dev/null || true
sudo cp -a /usr/local/bin/hcm-heartbeat "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo mkdir -p "/root/hcm-heartbeat-backup-$TS/state"
sudo cp -a /var/lib/hcm-heartbeat/state.json "/root/hcm-heartbeat-backup-$TS/state/" 2>/dev/null || true
sudo cp -a /var/lib/hcm-heartbeat/registry.sqlite3* "/root/hcm-heartbeat-backup-$TS/state/" 2>/dev/null || true
sudo systemctl --no-pager status hcm-heartbeat.service > "/root/hcm-heartbeat-backup-$TS/status.before.txt" || true
```

### Pre-Install Verification

```sh
hostname
ip addr show
python3 --version
sudo python3 -m json.tool /etc/hcm-heartbeat/config.json >/dev/null
curl -fsS http://192.168.20.26:6004/status | python3 -m json.tool
```

Expected config values before proceeding:

- `role` is `conflict`.
- `bind_address` is `192.168.20.26`.
- `advertise_ip` is `192.168.20.26`.
- `port` is `6004`.

### Install

From a complete HomeControl checkout copied to the host:

```sh
cd /path/to/Home_Controller/00_Heartbeat
sudo ./install.sh conflict
```

The installer preserves an existing `/etc/hcm-heartbeat/config.json`; review and
merge new template fields manually rather than replacing live config blindly.

### Post-Install Verification

```sh
sudo systemctl --no-pager status hcm-heartbeat.service
sudo journalctl -u hcm-heartbeat.service -n 80 --no-pager
test -f /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
sudo python3 -m py_compile /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
curl -fsS http://192.168.20.26:6004/status | python3 -m json.tool
sudo ls -l /var/lib/hcm-heartbeat/registry.sqlite3*
```

If Jetson is still running the older daemon, verify Conflict accepts the legacy
colon-form heartbeat and reports Jetson under normalized ID once a heartbeat has
arrived.

### Rollback

```sh
TS="<backup timestamp>"
sudo systemctl stop hcm-heartbeat.service
sudo cp -a "/root/hcm-heartbeat-backup-$TS/hcm-heartbeat.service" /etc/systemd/system/hcm-heartbeat.service 2>/dev/null || true
sudo rm -rf /usr/local/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/lib" /usr/local/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/hcm-heartbeat" /usr/local/bin/hcm-heartbeat 2>/dev/null || true
sudo cp -a "/root/hcm-heartbeat-backup-$TS/config.json" /etc/hcm-heartbeat/config.json
sudo mkdir -p /var/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/state/"* /var/lib/hcm-heartbeat/ 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl start hcm-heartbeat.service
sudo systemctl --no-pager status hcm-heartbeat.service
curl -fsS http://192.168.20.26:6004/status | python3 -m json.tool
```

## Jetson Commands

Run these commands on `jetson` (`192.168.20.27`) only after Conflict has been
updated and verified.

### Backup

```sh
TS="$(date -u +%Y%m%dT%H%M%SZ)"
sudo mkdir -p "/root/hcm-heartbeat-backup-$TS"
sudo cp -a /etc/hcm-heartbeat/config.json "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo cp -a /etc/systemd/system/hcm-heartbeat.service "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo cp -a /usr/local/lib/hcm-heartbeat "/root/hcm-heartbeat-backup-$TS/lib" 2>/dev/null || true
sudo cp -a /usr/local/bin/hcm-heartbeat "/root/hcm-heartbeat-backup-$TS/" 2>/dev/null || true
sudo mkdir -p "/root/hcm-heartbeat-backup-$TS/state"
sudo cp -a /var/lib/hcm-heartbeat/state.json "/root/hcm-heartbeat-backup-$TS/state/" 2>/dev/null || true
sudo cp -a /var/lib/hcm-heartbeat/registry.sqlite3* "/root/hcm-heartbeat-backup-$TS/state/" 2>/dev/null || true
sudo systemctl --no-pager status hcm-heartbeat.service > "/root/hcm-heartbeat-backup-$TS/status.before.txt" || true
```

### Pre-Install Verification

```sh
hostname
ip addr show
python3 --version
sudo python3 -m json.tool /etc/hcm-heartbeat/config.json >/dev/null
curl -fsS http://127.0.0.1:6004/status | python3 -m json.tool
curl -fsS http://192.168.20.26:6004/status | python3 -m json.tool
```

Expected config values before proceeding:

- `role` is `device`.
- `advertise_ip` is `192.168.20.27`.
- `conflict_address` is `192.168.20.26`.
- `port` is `6004`.

### Install

From a complete HomeControl checkout copied to the host:

```sh
cd /path/to/Home_Controller/00_Heartbeat
sudo ./install.sh jetson
```

### Post-Install Verification

```sh
sudo systemctl --no-pager status hcm-heartbeat.service
sudo journalctl -u hcm-heartbeat.service -n 80 --no-pager
test -f /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
sudo python3 -m py_compile /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
curl -fsS http://127.0.0.1:6004/status | python3 -m json.tool
curl -fsS http://192.168.20.26:6004/status | python3 -m json.tool
```

Expected results:

- Jetson `/status` reports `device_id` as 12 lowercase hex characters.
- Jetson `status.peer.online` becomes true after the next heartbeat.
- Conflict registry contains one normalized Jetson row, not separate colon-form
  and normalized rows.
- Addresses remain `192.168.20.27` and `192.168.20.26`.

### Rollback

```sh
TS="<backup timestamp>"
sudo systemctl stop hcm-heartbeat.service
sudo cp -a "/root/hcm-heartbeat-backup-$TS/hcm-heartbeat.service" /etc/systemd/system/hcm-heartbeat.service 2>/dev/null || true
sudo rm -rf /usr/local/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/lib" /usr/local/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/hcm-heartbeat" /usr/local/bin/hcm-heartbeat 2>/dev/null || true
sudo cp -a "/root/hcm-heartbeat-backup-$TS/config.json" /etc/hcm-heartbeat/config.json
sudo mkdir -p /var/lib/hcm-heartbeat
sudo cp -a "/root/hcm-heartbeat-backup-$TS/state/"* /var/lib/hcm-heartbeat/ 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl start hcm-heartbeat.service
sudo systemctl --no-pager status hcm-heartbeat.service
curl -fsS http://127.0.0.1:6004/status | python3 -m json.tool
```

## Final Gate Before Deployment Approval

Before deployment approval:

1. Run `python3 --version` on both hosts and confirm Python 3.6 runtime
   behavior with `py_compile` and a local `--config ... show` invocation.
2. Confirm Conflict was updated and accepts the current Jetson heartbeat before
   changing Jetson.
3. Confirm backups include `/etc/hcm-heartbeat/config.json`,
   `/usr/local/lib/hcm-heartbeat`, `/usr/local/bin/hcm-heartbeat`,
   `/etc/systemd/system/hcm-heartbeat.service`, and
   `/var/lib/hcm-heartbeat/registry.sqlite3*`.
4. Keep VLAN 20 and TCP 6004 unchanged.
5. Do not enable VLAN 60 binding or VLAN 40 control assignment during this
   rollout.
