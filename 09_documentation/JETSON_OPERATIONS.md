# Jetson HCM Operations Guide

This guide consolidates the Jetson deployment runbook, systemd relationships,
and HCM watchdog behavior. It describes the verified development host only.
Architecture authority remains in the [white papers](whitepapers/README.md).

## Installed Development Topology

- Ethernet: `192.168.20.27`
- Wi-Fi: `192.168.20.25`
- HCM API/UI: `http://192.168.20.27:8080`
- HCM application: Docker container `hcm-test`
- PostgreSQL: `hcm-postgres` on a private Docker network
- HCM data: `/srv/hcm-data/homecontrol`
- PostgreSQL data: `/srv/hcm-data/postgres`
- Heartbeat V3: native host service `hcm-heartbeat.service`
- Conflict Manager: `192.168.20.26:6004`
- Watchdog: `hcm-watchdog.timer`

The active control and supervision path is VLAN 20. VLAN 40 is a future
placeholder and VLAN 60 is not active. The retired `hcm-routing.service`, route
rule 1100, and client-specific routing hook must not be restored.

## Services and Dependencies

| Unit | Role |
| --- | --- |
| `docker.service` | Container runtime |
| `hcm-postgres.service` | PostgreSQL container and persistent data dependency |
| `hcm.service` | HCM application container lifecycle |
| `hcm-heartbeat.service` | Independent host Heartbeat V3 daemon |
| `hcm-watchdog.service` | One-shot HCM liveness/recovery check |
| `hcm-watchdog.timer` | Watchdog schedule |

HCM depends on Docker and PostgreSQL readiness. Heartbeat V3 remains independent
of HCM/PostgreSQL health. The watchdog targets HCM application availability and
is not a safety authority.

Read-only inspection:

```sh
systemctl is-active docker hcm-postgres hcm hcm-heartbeat hcm-watchdog.timer
systemctl status hcm hcm-postgres hcm-heartbeat hcm-watchdog.timer --no-pager
systemctl cat --no-pager hcm.service hcm-postgres.service hcm-heartbeat.service hcm-watchdog.service hcm-watchdog.timer
sudo docker ps --filter name=hcm-test --filter name=hcm-postgres
ip -4 route get 192.168.20.26
curl -i http://192.168.20.27:8080/
```

The expected route to Conflict is Ethernet sourced from `192.168.20.27`.

## Deployment and Recovery

Use the unified deployment framework in [HCM Operations](HCM_OPERATIONS.md).
Repository unit files do not update installed units automatically. Preserve
Docker networks, PostgreSQL, USB storage, environment files, certificates,
Heartbeat V3, and watchdog state. Verify PostgreSQL before HCM, then HCM health,
then Conflict supervision.

Migrations are deliberate, not automatic:

```sh
10_scripts/homecontrol-db status
10_scripts/homecontrol-db migrate
```

Before a live migration, verify a backup, test against a clone where practical,
review status, apply deliberately, and verify HCM afterward.

## Watchdog

The versioned implementation is:

- `10_scripts/hcm-watchdog.py`
- `07_servises/systemd/hcm-watchdog.service`
- `07_servises/systemd/hcm-watchdog.timer`

It checks HCM liveness, counts consecutive failures, and may request an HCM-only
restart after its configured threshold. It must not intentionally restart
PostgreSQL, Heartbeat V3, or network routing. For planned HCM maintenance, stop
the systemd HCM service so intentional downtime is distinguishable from failure.

```sh
sudo /usr/local/sbin/hcm-watchdog --check-only
systemctl status hcm-watchdog.timer --no-pager
systemctl list-timers --all --no-pager | grep hcm-watchdog
sudo cat /var/lib/hcm-watchdog/state.json
```

A controlled container-kill recovery test was verified on 2026-10-10; PostgreSQL
and Heartbeat V3 remained active. A post-routing-cleanup crash-injection test is
not claimed. The watchdog is not proof of healthy transactions, USB storage,
fire input, relay outputs, CAN, or emergency lighting.

## Secrets and Safety

Keep database credentials, update secrets, HMAC keys, TLS private keys, and
touchscreen PIN secrets outside Git, reports, and command lines. A healthy HCM
dashboard, database, or watchdog does not validate physical I/O or field wiring.
Inspect the live host before changing anything if it differs from this guide.

## Build identity and safety-route acceptance

See [the safety/deployment audit](HCM_SAFETY_DEPLOYMENT_AUDIT.md) for the code-only
findings and the independent Conflict/HCM input paths. The Jetson Docker build
requires `--build-arg HCM_GIT_SHA=<full-release-SHA>`. Runtime identity is available
at `/api/v1/version`; updating Git alone does not update the running image.
After an approved deployment, run:

```sh
python3 10_scripts/hcm_verify.py --url http://192.168.20.27:8080 --expected-sha <full-release-SHA>
```

This reads version, health, the unauthenticated safety-status response (must be
401), and static JavaScript. It does not read GPIO or trigger fire actions.
The deployment helper runs these checks before declaring success and restores
the original container on failure. It preserves the independent host services.
