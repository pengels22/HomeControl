# HCM Operations Guide

This guide consolidates HCM user synchronization, module identity and role
management, mTLS deployment boundaries, and the unified configuration/deployment
framework. Architecture authority remains in the [white papers](whitepapers/README.md).
Nothing here authorizes deployment or physical commissioning.

## Central Users

HCM is the authoritative user database. After a central user creation, password
change, reset, or role change, HCM sends an identity-bound snapshot over the
authenticated module-control session. Reconnecting modules receive the current
snapshot during the normal configuration exchange.

Snapshots contain usernames, enabled state, ADMIN/READONLY role, and the
PBKDF2-SHA256 verifier and parameters. They never contain plaintext passwords,
sessions, tokens, private keys, or GitHub credentials. Each snapshot includes
the target permanent device ID, content revision, issue sequence, and checksum.
Modules reject old sequences, wrong device IDs, malformed roles, unsupported
verifiers, and checksum mismatches.

Offline verification necessarily increases password-guessing exposure because an
enrolled module holds a verifier. Existing PBKDF2 settings, login throttling,
expiry, CSRF protection, restrictive cookies, and audit logging remain required.
Central revocations cannot affect an isolated module until its authenticated
session reconnects.

LAB1's pre-existing local bootstrap remains separate. A colliding synchronized
username is renamed with the `recovery:` prefix and the protected bootstrap file
is updated; it is not a second central user directory. LAB1 remains identified
as `2ccf675d3414`, role `LCM`, simulation-enabled, physical-output-disabled,
with no logical bindings.

## Module Identity and mTLS

The HCM module listener on TCP 6501 is intended to be published only with
mutual TLS. Each client certificate has exactly one device URI SAN:

```text
urn:homecontrol:device:<normalized-device-id>
```

For LAB1 this is `urn:homecontrol:device:2ccf675d3414`. The CA private key
stays on the operator workstation and never enters Jetson, LAB1, Git, or Docker
images. Secrets, certificates, database passwords, bearer tokens, and HMAC keys
remain outside the repository.

HCM rejects registration before assignment or database writes when the client
certificate is missing, lacks a device URI SAN, has duplicate or malformed SANs,
or disagrees with the claimed device ID. When the secure listener guard is
enabled, startup requires:

```text
HCM_TLS_ENABLED=true
HCM_TLS_REQUIRE_CLIENT_CERT=true
HCM_MODULE_CERT_IDENTITY_REQUIRED=true
HCM_ALLOW_INSECURE_MODULE_LISTENER=false
```

The insecure listener override is for explicit local development only.

Before an approved mTLS maintenance window, inspect certificates locally
without printing private keys:

```sh
openssl x509 -in ~/HomeControl-PKI/ca/homecontrol-ca.crt -noout -subject -issuer -dates
openssl x509 -in ~/HomeControl-PKI/hcm/hcm-server.crt -noout -subject -issuer -dates -ext subjectAltName
openssl x509 -in ~/HomeControl-PKI/lab1/lab1-client.crt -noout -subject -issuer -dates -ext subjectAltName
```

The Jetson environment uses `/etc/hcm/pki/homecontrol-ca.crt`,
`/etc/hcm/pki/hcm-server.crt`, and `/etc/hcm/pki/hcm-server.key`. The key is
root-owned and mode `0600`; public certificates are root-owned and mode `0644`.
Copying LAB1 client material and restarting the listener require a separate
approved maintenance workflow.

## Role Switching

Keep these concepts separate:

- permanent hardware identity;
- registered module type;
- requested/assigned operational role;
- reported operational role.

Only authenticated HCM ADMIN users may request an allowed role transition. HCM
requires explicit confirmation, an enabled device, an authenticated online
control session, and no active logical bindings requiring review. The existing
mTLS framed JSON session carries a `set_module_role` command with an operation
ID and `simulation_required: true`.

An acknowledgement moves a transition only to `ACCEPTED` or `REJECTED`. HCM
marks it `CONFIRMED` only after a later heartbeat/state report confirms the
requested role with `simulation=true` and `physical_outputs_enabled=false`.
Persisted statuses are `PENDING`, `SENT`, `ACCEPTED`, `APPLYING`, `CONFIRMED`,
`REJECTED`, `TIMED_OUT`, and `FAILED`; only one active transition per device is
allowed.

LAB1 remains `lab1` at `192.168.20.36` on VLAN 20. Role changes preserve device
identity, hostname, IP, VLAN, simulation, physical-output inhibition, and
commissioning state. They do not alter bindings, GPIO, relays, dimmers, CAN,
I2C, SPI, or network configuration.

The repository helper `11_scripts/lab1_role_agent.py` is safe for a reviewed
manual deployment: it validates device ID, operation ID, role, and
`simulation_required`, updates only the existing role field, preserves identity
and output-inhibition fields, and does not touch hardware interfaces. Do not
install it or stop `homecontrol-lab.service` without an approved LAB1
maintenance window. Rollback is restoring the prior agent and restarting only
that service.

Relevant API endpoints:

- `GET /api/v1/module-roles`
- `GET /api/v1/module-role-transitions/{operation_id}`
- `POST /api/v1/modules/{device_id}/role`

## Configuration and Deployment

The shared deployment framework validates manifests, device inventory, release
SHA, authentication requirements, backup declarations, rollback references, and
target-specific safety gates. It supports dry-run planning and records reports
under `runtime/deployments` or `HC_DEPLOY_REPORT_DIR`.

```sh
homecontrol status
homecontrol inventory
homecontrol deploy --dry-run
homecontrol preflight --remote
homecontrol verify --remote --target lab1
homecontrol rollback --target jetson --deployment-id <deployment-id> --yes
```

State-changing deployments require an explicit target and `--yes`; a bare
`deploy --yes` is rejected. SSH uses configured aliases and verified host keys.
The framework never stores secrets in reports or command arguments.

Every target requires a deployment-specific backup and rollback declaration.
Jetson rollback preserves Docker networks, PostgreSQL USB storage, environment
files, certificates, watchdogs, and the prior container. LAB1 rollback preserves
hostname, IP, identity, simulation-only state, physical-output inhibition,
certificates, HMAC state, and role history. RMC firmware is never handled by a
generic Linux adapter.

Normal HCM startup does not run migrations automatically. Review a backup and
migration status before deliberate database changes:

```sh
11_scripts/homecontrol-db status
11_scripts/homecontrol-db migrate
```

LAB1 acceptance requires valid state JSON, device ID `2ccf675d3414`, hostname
`lab1`, `simulation=true`, `physical_outputs_enabled=false`, active required
services, and a fresh authenticated Conflict heartbeat. Any mismatch is a
deployment failure.

## Boundaries

Do not restart PostgreSQL, host Heartbeat V3, the watchdog, networking, or LAB1
as part of ordinary HCM container updates. Preserve persistent databases,
certificates, USB storage, network attachments, and independent supervision.
Software tests and UI/database commissioning do not prove physical GPIO,
relay, dimmer, HVAC, emergency-light, or CAN safety.

## Fire Inputs and GPIO

The fire-input software path is complete, but physical wiring, electrical
conditioning, maintenance-lockout behavior, and live monitoring remain
uncommissioned. The identifiers are case-sensitive and both inputs use 250 ms
debounce.

| Controller | Sensor | Header pin | Linux/SoC mapping | HIGH means |
| --- | --- | ---: | --- | --- |
| HCM Jetson | `fire_alarm_s` | 38 | `/dev/gpiochip0`, line 159 | fire alarm active |
| HCM Jetson | `fire_alarm_P` | 40 | `/dev/gpiochip0`, line 158 | 120 V AC present |
| Conflict Manager | `fire_alarm_s` | 38 | PI4, SoC GPIO 260, `/dev/gpiochip1`, line 260 | fire alarm active |
| Conflict Manager | `fire_alarm_P` | 40 | PI3, SoC GPIO 259, `/dev/gpiochip1`, line 259 | 120 V AC present |

Each processor uses its own independent three-wire contact arrangement: NO to
that processor's 3.3 V, NC to its ground, and COM to its GPIO. Supplies and
grounds are not shared. Debounce does not provide open-wire detection or replace
input protection and wiring supervision.

Inputs report `LOW`, `HIGH`, `UNKNOWN`, or a read fault distinctly. Unavailable
or faulty input is never treated as normal. `fire_alarm_s` feeds the existing
debounced HCM SafetyController fire path. `fire_alarm_P` reports `present`,
`absent`, or `unknown`; AC loss is not a fire event. Conflict monitors both
inputs independently through the existing heartbeat status snapshot, but its
monitor is disabled by default.

Linux GPIO access is read-only and only available through explicit construction.
No physical output path is enabled by this implementation. Existing life-safety
priority, maintenance lockout, HVAC shutdown, and logical command arbitration
remain authoritative. Physical wiring and live fire action require separately
approved validation; this documentation does not activate monitoring or deploy
to either host.
