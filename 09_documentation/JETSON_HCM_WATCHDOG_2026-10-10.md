# HCM Watchdog — Jetson Operational Reference

**Original controlled recovery validation:** 2026-10-10

The watchdog is an HCM application-availability mechanism. It is not a life-safety monitor.

Architecture authority: [current white papers](whitepapers/README.md).

## Current service role

Versioned files:

- `10_scripts/hcm-watchdog.py`
- `07_servises/systemd/hcm-watchdog.service`
- `07_servises/systemd/hcm-watchdog.timer`

The timer periodically runs the one-shot watchdog.

The watchdog:

- checks HCM application health;
- counts consecutive failures;
- can request an HCM-only restart after the configured threshold;
- does not intentionally restart PostgreSQL;
- does not intentionally restart Unified Heartbeat V3;
- does not manage current network routing.

The old `hcm-routing.service`, `hcm-update-routing` post-start hook, and route rule 1100 are retired.

## Verified historical recovery test

A controlled `docker kill hcm-test` test on 2026-10-10 produced:

- first failure;
- second failure;
- third failure;
- HCM application restart;
- subsequent healthy check.

PostgreSQL and Heartbeat V3 remained active after that controlled test.

That test occurred before later Ethernet-first routing cleanup. A second crash-injection test after the routing cleanup is not claimed.

## Current host addresses

- Jetson Ethernet: `192.168.20.27`
- Jetson Wi-Fi: `192.168.20.25`
- Conflict Manager: `192.168.20.26`

## Basic inspection

```sh
sudo /usr/local/sbin/hcm-watchdog --check-only
systemctl status hcm-watchdog.timer --no-pager
systemctl list-timers --all --no-pager | grep hcm-watchdog
sudo cat /var/lib/hcm-watchdog/state.json
```

For planned HCM maintenance, stop the systemd HCM service rather than only stopping the container so the watchdog can distinguish maintenance from an application failure.

## Recovery boundaries

The watchdog must not be used as proof that:

- PostgreSQL transactions are healthy;
- USB storage is healthy;
- physical fire input is healthy;
- relay outputs are safe;
- CAN is healthy;
- emergency lighting has actuated.

Unified Heartbeat V3 remains the independent host-level supervisory service.

## Installation note

Changing repository files does not update installed Jetson units automatically.

Use the approved deployment framework or a deliberate reviewed installation process, and verify the live files afterward.

## Known limits

The watchdog is an HTTP/application liveness mechanism, not a complete functional transaction monitor.

Restart suppression/alert-delivery behavior should be separately validated before relying on it for unattended production operations.
