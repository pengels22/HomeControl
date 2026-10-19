# Jetson HCM systemd reference

This file documents the current expected Jetson development service relationships.

For overall architecture, see [whitepapers/README.md](whitepapers/README.md).

## Expected units

| Unit | Role |
|---|---|
| `docker.service` | Container runtime |
| `hcm-postgres.service` | Starts/owns the PostgreSQL development container and persistent data dependency |
| `hcm.service` | Starts/stops the HCM application container |
| `hcm-heartbeat.service` | Independent Unified Heartbeat V3 host daemon |
| `hcm-watchdog.service` | One-shot HCM liveness/recovery check |
| `hcm-watchdog.timer` | Periodic watchdog schedule |

`hcm-routing.service` is retired and is not a current dependency.

## Expected dependency direction

- HCM depends on Docker and PostgreSQL readiness.
- Heartbeat V3 is independent of HCM/PostgreSQL application health.
- The watchdog targets HCM availability and must not become the safety authority.
- PostgreSQL and Heartbeat V3 should not be restarted merely because the HCM app is restarted.

## Basic inspection

```sh
systemctl is-active docker hcm-postgres hcm hcm-heartbeat hcm-watchdog.timer
systemctl status hcm hcm-postgres hcm-heartbeat hcm-watchdog.timer --no-pager
systemctl cat --no-pager hcm.service hcm-postgres.service hcm-heartbeat.service hcm-watchdog.service hcm-watchdog.timer
```

## HCM application

The current development HCM is containerized as `hcm-test`.

The systemd unit is responsible for starting/stopping the known container and waiting for required dependencies.

Do not reintroduce the historical `hcm-routing.service`, route-rule 1100, or old `hcm-update-routing` post-start hook.

## PostgreSQL

PostgreSQL runs separately in `hcm-postgres` and uses persistent storage under `/srv/hcm-data/postgres`.

HCM restart should not destroy or recreate PostgreSQL data.

## Heartbeat

`hcm-heartbeat.service` is host-native and independent.

Its availability must not depend on the HCM Docker container or PostgreSQL.

## Watchdog

The watchdog timer periodically invokes the one-shot watchdog service.

The watchdog can recover HCM application failure but is not a complete system safety supervisor.

## Deployment note

Repository unit files are source references. Editing Git does not automatically update installed files on the Jetson.

Use the approved deployment framework or deliberate operator installation and verify the resulting live unit definitions.
