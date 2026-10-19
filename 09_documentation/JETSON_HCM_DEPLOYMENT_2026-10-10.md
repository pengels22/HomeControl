# Jetson HCM Deployment Runbook

**Purpose:** current operational reference for the verified Jetson development HCM deployment.

Architecture and design authority lives in [the white papers](whitepapers/README.md). This runbook documents the installed development host and should not be used to override current architecture.

## Current verified topology

Jetson Xavier NX development host:

- Ethernet: `192.168.20.27`
- Wi-Fi: `192.168.20.25`
- HCM API/UI: `http://192.168.20.27:8080`
- HCM application: Docker container `hcm-test`
- PostgreSQL: Docker container `hcm-postgres` on a private Docker network
- HCM data root: `/srv/hcm-data/homecontrol`
- PostgreSQL data: `/srv/hcm-data/postgres`
- Unified Heartbeat V3: native host service `hcm-heartbeat.service`
- Conflict Manager: `192.168.20.26:6004`
- HCM watchdog: `hcm-watchdog.timer`

Current control/supervision is VLAN 20. No VLAN 40 migration has been performed. VLAN 60 is not part of the current approved architecture.

## Service model

Expected host services:

- `docker.service`
- `hcm-postgres.service`
- `hcm.service`
- `hcm-heartbeat.service`
- `hcm-watchdog.timer`

The retired `hcm-routing.service` dependency and old client-specific policy-routing hook are not part of the current deployment and must not be restored.

## Operational verification

Read-only checks:

```sh
systemctl is-active hcm hcm-postgres hcm-heartbeat hcm-watchdog.timer
sudo docker ps --filter name=hcm-test --filter name=hcm-postgres
ip -4 route get 192.168.20.26
curl -i http://192.168.20.27:8080/
```

Expected route to Conflict is Ethernet sourced from `192.168.20.27`.

## Application/data boundaries

HCM application runs in Docker.

PostgreSQL is separate from the HCM application container.

Unified Heartbeat V3 is a native host service and remains independent of HCM and PostgreSQL.

Do not make HCM container health a prerequisite for the host heartbeat daemon.

## Database migrations

Normal HCM startup does not automatically run schema migrations.

Use the repository database tool explicitly:

```sh
10_scripts/homecontrol-db status
10_scripts/homecontrol-db migrate
```

Before applying migrations to the live Jetson database:

1. verify backup;
2. test against a clone when practical;
3. review migration status;
4. apply deliberately;
5. verify HCM after migration.

## Deployment framework

Use the current unified deployment tooling documented in:

[UNIFIED_CONFIGURATION_DEPLOYMENT_2026-10-11.md](UNIFIED_CONFIGURATION_DEPLOYMENT_2026-10-11.md)

Do not reuse older phase-specific image names or historical Phase 3/4 rebuild recipes from Git history.

## Secrets

Deployment secrets remain outside Git.

Examples include:

- database credentials;
- update request secrets;
- heartbeat HMAC secret;
- TLS private keys/certificates;
- touchscreen PIN lookup secret.

Do not paste secret values into issues, documentation, deployment reports, or commits.

## Watchdog

The watchdog checks HCM application liveness and can restart HCM without intentionally restarting PostgreSQL or Heartbeat V3.

See:

[JETSON_HCM_WATCHDOG_2026-10-10.md](JETSON_HCM_WATCHDOG_2026-10-10.md)

The watchdog is an availability mechanism, not a life-safety controller.

## Physical safety boundary

A healthy HCM dashboard, database, or watchdog does not validate:

- physical fire GPIO;
- RCM/LCM physical outputs;
- HVAC field wiring;
- emergency-light operation;
- CAN physical layer.

Those require separate HIL/commissioning evidence.

## Recovery principle

When recovering the host:

1. preserve persistent data;
2. keep Heartbeat V3 independent;
3. avoid ad-hoc network/routing changes;
4. restore HCM through the current deployment adapter/runbook;
5. verify PostgreSQL before HCM;
6. verify HCM health;
7. verify Conflict heartbeat separately.

If the installed host differs from this runbook, inspect the live host before making changes rather than applying historical assumptions.
