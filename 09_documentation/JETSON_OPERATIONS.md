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

### Authentication schema prerequisite

The October 19 deployment exposed a missing `auth_login_rate_limits` table in the
older installed database. Image identity/health alone did not validate login.
The deployment adapter now checks the candidate authentication schema inside the
existing app container before replacement; HCM startup also checks it read-only.
Runtime acceptance additionally requires JSON 401 for a random nonexistent login.
This does not validate a user's password, but catches the missing-table regression.

Migration status inspection is read-only. For a reviewed older installation,
back up PostgreSQL, restore/test a clone, then explicitly select the required
migrations rather than rerunning all historical migrations blindly:

```sh
python 10_scripts/homecontrol-db status
python 10_scripts/homecontrol-db migrate --version 6 --version 7
```

006 adds touchscreen authentication schema; 007 adds normal-login rate limiting,
an active-session index, and the current output-intent source constraint. Verify
existing source values before applying 007. Migrations remain a deliberate
operator action, never an automatic side effect of starting the HCM application.
A previous application container can be restored while retaining these additive
schema changes. Backups must remain host-local and access-restricted.

Real I/O mode is distinct from commissioned output permission. Do not relabel
unavailable hardware as simulated or mark modules commissioned without evidence.
The existing LAB1 adapter is simulation-only; production module deployment needs
the confirmed target bus, attached hardware, and commissioned profile.

### Physical fire input access (Jetson Linux 4.9)

During an explicitly approved input rollout, run
`sudo python3 10_scripts/hcm_gpio_access.py --apply` on the Jetson. The tool checks
chip label `tegra-gpio` and line names `I2S0_DIN` (159, FIRE/header 38) and
`I2S0_DOUT` (158, AC/header 40), without reading values or changing direction.
It provisions a dedicated `hcm-gpio` group and a chip-specific persistent udev
rule, mode 0640. It creates `/etc/hcm/safety-inputs.json` only if absent:

```json
{"gpio_abi": "v1", "connected_inputs": []}
```

Only add a signal name to `connected_inputs` after its physical wiring has been
confirmed. GPIO LOW is not evidence of connected wiring. Unconfirmed contacts
report Unknown with `fault: true`; they cannot establish Normal. This explicit
wiring record is preserved on redeploy. Missing wiring records also leave inputs
Unknown. This is not electrical open-wire detection after commissioning.

The supported Docker clone helper binds that file read-only, adds the dedicated
supplementary group and maps only `/dev/gpiochip0` with cgroup read access. It
refuses broad privileged mode. GPIO chip access is not a per-line kernel ACL:
the application transport restricts requests to input flags and refuses lines
already owned or configured as outputs. No output or pull-setting ioctl is used.
The ABI v1 transport is required by the installed kernel; image libgpiod v2
requires a newer kernel. Polarity and 250 ms debounce remain unchanged.

The independent Conflict inputs require their own confirmed wiring list and
verified profile. Its installer now includes `gpio_inputs.py`; disabling its
monitor keeps both contacts Unknown. Never infer installed wiring from software
pin mappings or substitute Conflict values for HCM inputs. Access configuration
alone is a partial rollout, not physical fire-system commissioning.
