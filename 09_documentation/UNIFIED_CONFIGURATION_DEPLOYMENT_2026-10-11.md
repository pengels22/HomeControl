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
homecontrol preflight --remote
homecontrol verify
homecontrol verify --remote
homecontrol history
homecontrol rollback --target lab1
```

Reports are stored under `runtime/deployments` by default, or under
`HC_DEPLOY_REPORT_DIR` in tests. The CLI does not store or print secrets.

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

- Conflict must use SQLite online backup and must not overwrite its registry or
  heartbeat authentication secret. Rollback requires an explicit backup path.
- Jetson rollback must preserve Docker networks, PostgreSQL USB storage,
  environment files, certificates, watchdogs, and rollback containers. The
  adapter preserves the previous HCM container as `hcm-rollback-before-deploy`
  before replacing `hcm-test`.
- LAB1 rollback must preserve hostname, IP, device identity, simulation-only
  state, physical-output-disabled state, certificates, HMAC secret, and role
  history.
- RMC rollback is firmware-specific and must never flash hardware through a
  generic Linux adapter.

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

## Known Limitations

- The SSH deployment path is implemented but has only been exercised with mocked
  transports in automated tests during this commit. A live dry-run/verification
  report should be reviewed before first deployment.
- Jetson container replacement now uses a Docker API helper to clone the
  inspected container configuration and swap only the application image, but it
  still must be validated against the actual live `hcm.service` and Docker
  inspect output before first release.
- Jetson database migrations remain out of scope and require a separately
  approved plan.
- LAB1 deployment updates only the role helper after confirming the installed
  simulation layout; it does not replace the full persistent agent.
- Secure bootstrap for untrusted newly discovered devices is not implemented.
- HCM database fields for deployment status are not migrated in this foundation
  pass.
- Rollback is application-level and adapter-specific; unsafe database rollback
  still stops for manual intervention.
