# Unified Configuration, Commissioning, and Deployment Framework

Date: 2026-10-11

## Repository Audit Findings

- `06_config/01_HCM/install.sh` is a legacy native Python installer and is not
  compatible with the verified live Jetson Docker/PostgreSQL deployment.
- Linux module folders `02_SIM` through `05_PNL` used `06_config/common` and
  branch-based Git updates. The compatibility helper remains available, but now
  accepts `HC_RELEASE_SHA` for deterministic checkout.
- `06_config/05_PNL/install.sh` contained an `INSTALL_RwOOT` typo in its
  fallback path. This has been corrected.
- The legacy common helper used `rsync --delete` for source-repo installs. That
  destructive delete behavior has been removed.
- Conflict, Jetson, and LAB1 already have independent deployment/runbook
  concerns. The new framework models them as separate packages instead of
  forcing them through generic module installers.
- RMC is firmware, not Linux. Its manifest uses a firmware adapter and does not
  expose Linux install/update scripts.
- HCM commissioning already has identity and registry work from Phase 4. The new
  package-selection hook is planning-only and does not execute remote code.

## Directory Structure

Each supported package under `06_config` now owns a `manifest.yaml`.

- `01_HCM`: Jetson HCM Docker package model. Its legacy install script remains
  documented as not approved for the live Jetson.
- `02_SIM`, `03_LCM`, `04_RCM`, `05_PNL`: Linux module packages with legacy
  installers and unified update/verify/rollback wrappers.
- `06_RMC`: firmware-only package.
- `07_CONFLICT`: Conflict Heartbeat V3 supervisor package model.
- `08_LAB`: LAB1 simulation package model.
- `10_Common`: shared manifest validation, inventory, release pinning, planning,
  wrapper scripts, and documentation.

## Manifest Rules

`06_config/10_Common/manifest.py` validates schema version, device type, package
folder, hardware compatibility fields, deployment adapter, service names,
configuration paths, rollback requirements, safety flags, and required
authentication. Unknown device types, unsafe file paths, unsupported actions,
and Linux packages without the expected script entry points are rejected.

## Shared Deployment Engine

`06_config/10_Common/engine.py` resolves one immutable Git SHA, validates all
selected manifests against inventory, produces idempotent dry-run plans, writes
persistent JSON reports, and can execute approved deployments through
`06_config/10_Common/transport.py`. SSH uses the operator's configured aliases,
requires host-key verification, and does not store passwords, private keys, or
secrets.

Live adapters are implemented for Jetson Docker, Conflict Heartbeat V3, and LAB1
simulation. They run remote preflights before changing files or services, stage a
single release artifact, and record per-step outcomes. Standard automated tests
mock the SSH transport and do not contact live hosts.

## Mac CLI

The `homecontrol` console script is provided by `homecontrol_cli.py`:

```bash
homecontrol status
homecontrol inventory
homecontrol deploy --dry-run
homecontrol deploy --target jetson --release <full-sha> --dry-run
homecontrol deploy --target jetson --release <full-sha> --yes
homecontrol deploy --all --release <full-sha> --yes
homecontrol preflight --remote
homecontrol verify
homecontrol verify --remote
homecontrol history
homecontrol rollback --target lab1
```

Reports are stored under `runtime/deployments` by default, or under
`HC_DEPLOY_REPORT_DIR` in tests. The CLI does not store or print secrets.

Dry-run planning may inspect the fleet by default, but state-changing deploys
must be explicit: use either `--target DEVICE --yes` for a single device or
`--all --yes` for a fleet rollout. A bare `deploy --yes` is rejected so an
operator cannot accidentally expand a single-device deployment into a fleet
deployment. Target-specific read-only verification is available with
`homecontrol verify --remote --target lab1`.

## HCM Commissioning Integration

`01_HCM/deployment_selection.py` exposes a shared package-selection hook for
commissioning plans. It keeps hardware identity separate from operational role:
LAB1 keeps package `08_LAB` even when simulating RCM, SIM, or LCM behavior.
The hook returns `pending_admin_approval` and does not grant SSH access,
provision secrets, or execute scripts.

Secure bootstrap for newly discovered devices remains a design prerequisite.
Until a tested bootstrap transport exists, HCM must leave such devices pending
commissioning.

## Configuration Categories

- Repository defaults: manifests, templates, and scripts committed under
  `06_config`.
- Device-specific configuration: identity, trusted endpoints, state files,
  registries, installed release records, and known-good release references.
- Secrets: certificates, HMAC secrets, database passwords, bearer tokens, and
  private keys. These must remain outside Git and outside command-line
  arguments.

Ordinary deployments must preserve device identity, network configuration,
operational state, persistent databases, certificates, and secrets.

## Backup and Rollback

The framework requires rollback and backup declarations in every manifest.
Actual live backup and rollback are adapter-specific:

- Conflict must use a deployment-specific application backup directory and must
  not overwrite its active registry, configuration, or heartbeat authentication
  secret. The SQLite online backup in that directory is disaster-recovery
  evidence only; automatic application rollback does not replace the active
  registry database.
- Jetson rollback must preserve Docker networks, PostgreSQL USB storage,
  environment files, certificates, watchdogs, and rollback containers. The
  adapter preserves the previous HCM container under a deployment-specific
  `hcm-rollback-<deployment-id>` name before replacing `hcm-test`; existing
  rollback containers are never overwritten or deleted automatically. Recovery
  decisions are based on immutable Docker container IDs rather than names alone.
- LAB1 rollback must preserve hostname, IP, device identity, simulation-only
  state, physical-output-disabled state, certificates, HMAC secret, and role
  history.
- RMC rollback is firmware-specific and must never flash hardware through a
  generic Linux adapter.

## LAB1 Post-Deployment Acceptance Criteria

LAB1 deployment is accepted only after the restarted device still proves all of
the following from read-only checks:

- The OS hostname resolves to `lab1`.
- `/opt/homecontrol-lab/state/module.json` is readable and valid JSON.
- The module state reports `device_id=2ccf675d3414` and `hostname=lab1`.
- `simulation` is exactly `true`.
- `physical_outputs_enabled` is exactly `false`.
- The existing role and key state fields match the state snapshot captured in
  the deployment-specific backup.
- `homecontrol-lab.service` is active.
- `hcm-heartbeat.service` is active.
- The heartbeat client exposes `/status`, reports LAB1's identity, and shows an
  online peer with a recent Conflict acknowledgment.

Any identity mismatch, malformed state file, disabled simulation flag, enabled
physical outputs flag, inactive required service, or observable heartbeat status
failure is a deployment failure. The new release marker is written only after
all LAB1 safety, service, and heartbeat checks pass.

The `/run/hcm-heartbeat/control.sock` path remains optional for LAB1 deployment
verification. The socket is for local heartbeat control/fault commands, not for
the normal client heartbeat path. Its absence is reported as metadata by service
checks and is not treated as a failure. Heartbeat delivery is instead checked by
TCP reachability to the configured Conflict endpoint and the installed
heartbeat daemon's existing `/status` endpoint. If `/status` is unavailable or
does not show a recent successful peer acknowledgment, deployment verification
fails rather than treating an active systemd service as proof of heartbeat
delivery.

Automatic LAB1 rollback restores the previous role helper and previous release
marker state, restarts only `homecontrol-lab.service`, and then runs the same
post-rollback safety, service, and heartbeat checks. A rollback that restores
files but leaves LAB1 with the wrong identity, non-simulation state, enabled
physical outputs, inactive required services, or failed observable heartbeat
health is reported as failed.

## Jetson Recovery Safety

The Jetson HCM deployment helper records the immutable Docker ID of the
currently running `hcm-test` container before any mutation. It refuses to start
if the deployment-specific rollback container name already exists. The
stop/rename/identity-check/create/start/health sequence is handled as one
recoverable operation:

- A failure before mutation reports failure without deleting or renaming
  containers.
- A stop or rename failure inspects the actual container state before recovery.
- After rename, the rollback container must have the original immutable ID; an
  identity mismatch aborts and requires manual intervention.
- Replacement create/start/health failures attempt to remove only the known
  replacement container and restore the original container ID to `hcm-test`.
- Recovery never deletes a container whose identity cannot be tied to the failed
  replacement path.
- Existing rollback containers are treated as protected recovery points and are
  never overwritten as part of a later deployment.

If the helper cannot prove whether `hcm-test` or the rollback name refers to the
original container, it stops with a manual-intervention error rather than
performing destructive cleanup. PostgreSQL (`hcm-postgres`), Docker networks,
USB database storage, environment files, secrets, and independent Heartbeat V3
remain outside the HCM container swap.

After a successful deployment or successful recovery, the name `hcm-test` must
refer to the intended application container so the existing `hcm.service`
continues to operate. A restored deployment is still reported as an unsuccessful
rollout; restoration success does not convert the failed deployment into a
deployment success.

## Conflict Backup And Rollback

Conflict deployment creates a unique recovery directory for every deployment:

```text
/var/backups/homecontrol-heartbeat/app-rollback-<deployment-id>
```

Predeployment gates check that the directory does not already exist, the active
heartbeat application files are present, the protected configuration and HMAC
secret metadata are readable via noninteractive `sudo`, the active registry
passes `PRAGMA integrity_check`, and `/var/backups` has sufficient free space.
These gates are read-only; they do not create test directories or backup files.

The backup script refuses to write into an existing destination. Before
installing the new heartbeat application it copies the previous application
files, systemd unit, safe metadata manifest, existing release marker or an
explicit marker-absent sentinel, and an online SQLite snapshot for disaster
recovery evidence. The active `/var/lib/hcm-heartbeat/registry.sqlite3`,
`/etc/hcm-heartbeat/config.json`, and HMAC secret file are not replaced by the
deployment or by automatic rollback.

After install, Conflict verification checks the service endpoint, registry
integrity, expected authorized and registered Jetson/LAB1 identities, and
unexpected active communication faults. The new
`/var/lib/hcm-heartbeat/homecontrol-release` marker is written only after those
checks pass.

Automatic Conflict rollback restores the previous application files and the
previous release marker state from the deployment-specific backup. If the marker
was absent before deployment, rollback removes the marker. Rollback then
restarts `hcm-heartbeat.service` and reruns heartbeat verification. If file
restoration, marker restoration, restart, endpoint health, registry integrity,
authorized-device verification, or fault checks fail, rollback is reported as
failed.

Recovery backup directories are retained for operator review. Clean them up only
after a later verified deployment and rollback window make the older recovery
point unnecessary. Retain at least the most recent known-good recovery point and
never remove a backup that is named in a deployment report still under review.

## Live Migration Plan

1. Run `homecontrol status` and `homecontrol deploy --dry-run` locally.
2. Run `homecontrol preflight --remote` to inspect live layouts without
   transferring files or restarting services.
3. Review the JSON deployment report and selected release SHA.
4. Run read-only target verification commands on Jetson, Conflict, and LAB1.
5. Provision required secrets out of band with owner-only permissions.
6. Stage release artifacts without restarting live services.
7. Verify staged manifests, configuration diffs, and backup availability.
8. Request explicit deployment approval.
9. Deploy one adapter at a time with rollback ready and live monitoring active.

The first live mutation should be a single-device command, for example:

```bash
.venv/bin/python homecontrol_cli.py deploy --target lab1 --dry-run
.venv/bin/python homecontrol_cli.py verify --remote --target lab1
.venv/bin/python homecontrol_cli.py deploy --target lab1 --yes
```

For Jetson and Conflict, use the same single-target pattern and review the
dry-run report before any approved live mutation:

```bash
.venv/bin/python homecontrol_cli.py deploy --target jetson --dry-run
.venv/bin/python homecontrol_cli.py verify --remote --target jetson
.venv/bin/python homecontrol_cli.py deploy --target jetson --yes

.venv/bin/python homecontrol_cli.py deploy --target conflict --dry-run
.venv/bin/python homecontrol_cli.py verify --remote --target conflict
.venv/bin/python homecontrol_cli.py deploy --target conflict --yes
```

Fleet-wide live deployment remains a separate explicit operation:

```bash
.venv/bin/python homecontrol_cli.py deploy --all --yes
```

## Known Limitations

- The SSH deployment path is implemented but has only been exercised with mocked
  transports in automated tests during this commit. A live dry-run/verification
  report should be reviewed before first deployment.
- Jetson preflight and replacement discover the actual Docker layout instead of
  assuming `/etc/hcm/hcm.env` exists. Docker inspection snippets avoid
  Python features missing from the Jetson host's Python 3.6.9. HCM API health is
  checked through the concrete Docker-published `8080/tcp` host binding, and
  ambiguous wildcard bindings are rejected rather than silently falling back to
  loopback.
- `10_scripts/hcm_docker_deploy.py` is compatible with Jetson host Python 3.6
  and derives its default post-swap and rollback health URL from the inspected
  `hcm-test` port bindings. The Docker API helper clones the inspected container
  configuration and swaps only the application image, while preserving
  environment entries, mounts, ports, restart policy, and network attachments.
  It fails closed before stopping `hcm-test` if the current container lacks the
  required HCM Docker networks or API port binding, or if it appears to contain
  PostgreSQL data storage. Rollback containers use deployment-specific names,
  preserve the previous container identity, and are refused if the target
  rollback name already exists. Failed swaps inspect both `hcm-test` and the
  deployment rollback name by immutable Docker ID before attempting recovery; an
  ambiguous or mismatched identity requires manual intervention instead of
  deleting an unidentified container.
- Conflict preflight uses noninteractive `sudo -n` for protected heartbeat
  metadata and reports only safe summaries such as auth mode, secret file
  presence/mode, registry integrity, service status, and TCP 6004 availability.
  The heartbeat endpoint is resolved from the protected config's bind or
  advertised address, so a supervisor bound only to `192.168.20.26:6004` is not
  incorrectly tested through loopback. Post-deployment verification uses
  `10_scripts/heartbeat_status_verify.py` to fetch `/status`, require HTTP 200,
  parse the actual JSON response, confirm the expected registered and authorized
  Jetson/LAB1 identities, and fail on unexpected active communication faults.
  Conflict deployment backups now use
  `/var/backups/homecontrol-heartbeat/app-rollback-<deployment-id>`, preserve
  the prior release marker or its absence, and refuse destination reuse.
  Automatic rollback restores only application files and marker state; it does
  not replace the active registry database, protected configuration, HMAC
  secret, authorized-device table, registered-device rows, heartbeat history, or
  their live permissions.
- LAB1 preflight validates the real `/opt/homecontrol-lab` layout, permanent
  identity, simulation-only state, disabled physical outputs, valid module
  state JSON, role presence, and required services without changing role state.
  Post-install and post-rollback verification repeats those safety checks after
  restart and compares the role plus identity/safety fields against the
  deployment backup's state snapshot. Service checks report each required
  systemd unit and its substate explicitly; the heartbeat control socket path is
  reported as metadata but is not treated as proof that the heartbeat service is
  active. The socket is optional for the installed heartbeat client's normal
  client-to-Conflict path: the daemon posts heartbeat packets directly to the
  configured Conflict endpoint over TCP 6004; the Unix socket is for local
  control/fault commands. LAB1 heartbeat verification therefore checks the
  configured Conflict destination over TCP and then reads the existing local
  heartbeat `/status` endpoint, requiring LAB1 identity and an online peer with
  a recent acknowledgment.
- LAB1 live deployment creates a deployment-specific backup under
  `/opt/homecontrol-lab/backups/<deployment-id>` before replacing
  `lab1_role_agent.py`. The backup preserves the previous role helper, module
  state snapshot, and release marker state, verifies the copied helper and state
  snapshot with `cmp`, and updates the `homecontrol-deploy-rollback` symlink. If
  post-replacement verification fails, rollback restores the previous helper
  and release marker before restarting only `homecontrol-lab.service`, then
  fails the rollout if the restored device does not pass the same safety,
  service, and observable heartbeat checks.
- Read-only SSH checks use bounded retries for transient transport failures such
  as banner-exchange or ProxyJump timeouts while preserving BatchMode,
  key-only authentication, strict host-key validation, and SSH aliases. Commands
  that can change remote state are not automatically retried after ambiguous
  transport failure.
- A deployment that reaches rollback is reported as `ROLLED BACK` for the target
  but as an unsuccessful rollout in the summary/CLI exit status. The release
  marker is written only after adapter health checks pass.
- Jetson database migrations remain out of scope and require a separately
  approved plan.
- LAB1 deployment updates only the role helper after confirming the installed
  simulation layout; it does not replace the full persistent agent.
- Secure bootstrap for untrusted newly discovered devices is not implemented.
- HCM database fields for deployment status are not migrated in this foundation
  pass.
- Rollback is application-level and adapter-specific; unsafe database rollback
  still stops for manual intervention.
