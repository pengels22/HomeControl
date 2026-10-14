# HCM Persistence Deployment Preparation - 2026-10-14

This is a read-only deployment-preparation record for the Git-backed
HomeControl storage architecture. No Jetson, Conflict, LAB1, Docker, systemd,
database, firmware, or physical-module changes were made while collecting this
record.

## Current Production Snapshot

- Production HCM release: `dd3b2fa42c5bf0087c5e0515fc44ecae10bc243b`.
- Running HCM container: `hcm-test`.
- Running HCM image: `homecontrol-hcm:dd3b2fa42c5bf0087c5e0515fc44ecae10bc243b`.
- HCM container user: `10001:10001`.
- HCM command: `python -m uvicorn 01_HCM.main:app --host 0.0.0.0 --port 8080`.
- Published ports: `192.168.20.27:8080` and `192.168.20.27:6501`.
- Docker networks: `hcm-control` and `hcm-internal`.
- Verified current container creation pattern: primary network is present at
  create time and secondary network is attached separately. Preserve this.
- Existing HCM bind mounts: `/etc/hcm/pki` mounted read-only.
- Existing PostgreSQL storage: `/srv/hcm-data/postgres` bind-mounted into
  `hcm-postgres`.
- `/var/lib/homecontrol` does not currently exist on Jetson.
- `/srv/hcm-data` exists and is the existing persistent storage root.
- Root filesystem had about 6.5 GB available during the read-only audit.
- Git and Python 3 are installed on the Jetson host.
- Python inside the HCM container is 3.13.16.
- HCM health endpoint returned `{"ok": true}`.
- `hcm.service` is active/enabled; `hcm-watchdog.timer` is active.
- Conflict heartbeat endpoint at `192.168.20.26:6004/status` reported healthy.
- Conflict registry reported LAB1 online/healthy, but direct LAB1 SSH was not
  available with the current key, so LAB1 simulation/output-inhibition was not
  independently re-read from `/opt/homecontrol-lab/state/module.json` in this audit.

## Required Deployment Adjustment

Before deploying a release that uses `HCM_STORAGE_ROOT=/var/lib/homecontrol`,
create the host directory and make it writable by the HCM container user:

```bash
sudo mkdir -p /srv/hcm-data/homecontrol
sudo chown 10001:10001 /srv/hcm-data/homecontrol
sudo chmod 0750 /srv/hcm-data/homecontrol
```

The replacement HCM container must include this bind mount:

```text
/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw
```

The existing `10_scripts/hcm_docker_deploy.py` helper now adds that bind mount
when cloning `hcm-test`, unless a `/var/lib/homecontrol` bind already exists.
It still creates the replacement container on its primary Docker network first
and connects additional networks before start.

No new PostgreSQL migration is required for the storage mount itself.

## Verification Before Deployment

Run these read-only checks before any future deployment:

```bash
ssh jetson@192.168.20.27 'sudo -n docker inspect hcm-test --format "{{json .Mounts}}"'
ssh jetson@192.168.20.27 'sudo -n test -d /srv/hcm-data/homecontrol && sudo -n ls -ld /srv/hcm-data/homecontrol'
ssh jetson@192.168.20.27 'curl -fsS --max-time 5 http://192.168.20.27:8080/api/v1/health'
ssh jetson@192.168.20.27 'curl -fsS --max-time 5 http://192.168.20.26:6004/status'
```

The first deployment using this storage should be HCM-only. Do not deploy to
LAB1, Conflict, or physical modules in the same operation.

## Post-Deployment Checks

After an approved HCM-only deployment, verify:

- `hcm-test` includes `/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw`.
- `/api/v1/health` returns OK.
- `/var/lib/homecontrol/config`, `/var/lib/homecontrol/logs`, `.git`, `.state`,
  and `.secrets` exist inside the container.
- `config/`, `logs/`, and `recovery-manifest.json` are the only storage content
  intended for Git tracking.
- Git status in Settings reports one of the approved labels:
  `Git Repository: Local Only`, `Git Repository: Up to Date`, or
  `Git Repository: Not Synced`.
- Conflict heartbeat remains healthy.
- LAB1 remains simulation-only with physical outputs disabled.

## Remaining Deployment Blockers

- The host storage directory has not yet been created or permissioned.
- The running HCM container does not yet include the `/var/lib/homecontrol` bind mount.
- Direct LAB1 state-file verification was blocked by SSH public-key access.
- No private GitHub credential was available for live GitHub push validation;
  local bare-remote integration tests were used instead.
