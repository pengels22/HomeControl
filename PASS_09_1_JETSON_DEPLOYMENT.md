# HomeControl Pass 9.1 Jetson Deployment Record

Date: 2026-10-24
Target: Jetson Xavier NX (`192.168.20.27`)
Deployment report: `runtime/deployments/hc-20261024T135233Z-f4473a4e.json`

## Deployed release

- Git SHA: `6735d03a74ae2db4456ce674aba197382f5b83bc`
- Image: `homecontrol-hcm:6735d03a74ae2db4456ce674aba197382f5b83bc`
- The image was built from the renamed `01_Heartbeat/`, `02_HCM/`, and `07_config/02_HCM/` layout.
- The live release marker and `/api/v1/version` report the same SHA.

## Recovery preparation

Recovery set retained at:

`/var/backups/homecontrol-deploy-20261024T134100Z`

Contents include the PostgreSQL custom dump, HCM data/configuration archive,
systemd unit captures, Docker inspection, restore notes, and SHA256 checksums.
The set is 352K, checksum verification passed, and the dump restored successfully
in an isolated `postgres:16` container. The restore contained 29 migration rows,
1 user, 1 module, and the PNL tables.

## Database

- PostgreSQL remained on its existing USB-backed volume.
- `homecontrol_schema_migrations` is complete through migration 029.
- No historical migration was rerun and no historical SIM records were deleted.
- PostgreSQL readiness passed after deployment.

## Acceptance checks

Passed:

- HCM health HTTP 200 and runtime SHA verification.
- `/pnl`, `/editor`, and `/dashboard` return HTTP 200.
- PNL panel configuration/state/events/sonic-policy endpoints reject unauthenticated access with HTTP 401.
- Random nonexistent login probe returns the expected JSON 401 through `hcm_verify.py`.
- Conflict Manager status HTTP 200; route is Ethernet via `eth0`, source `192.168.20.27`.
- Heartbeat V3 TCP 6004 reachable.
- HCM watchdog check reports healthy.
- Docker, PostgreSQL, HCM, Heartbeat, and watchdog timer are active.
- Physical safety inputs remain reported as Unknown/faulted because wiring is not commissioned; no physical output test was performed.

## SIM retirement and cleanup

No SIM systemd units, processes, or active SIM deployment paths remain on the
Jetson. The active `/opt/HomeControl` tree contains the Pass 9.1 removal and
only generic LAB/PNL simulation support that is unrelated to the retired SIM
module.

Retained recovery artifacts:

- Active image `homecontrol-hcm:6735d03...` (496 MB).
- One rollback image `homecontrol-hcm:0ce574e...` (496 MB) and its deployment rollback container.
- Current release staging directory `/tmp/homecontrol-release-6735d03...` for report-specific rollback tooling.
- The verified recovery set above.

Deleted HCM-scoped candidates after acceptance:

- Older release staging directories: `homecontrol-release-0ce574e...`, `-84f9f3...` (87 MB), `-b1ef32...`, `-bd549f...`, `-db51246...`, and `-ec3fa9...` (4.6 MB each).
- Source/debug staging: `homecontrol-5f1228e-src` (4.7 MB), `homecontrol-c48f2e7-src` (4.7 MB), `hcm-oldcompat-homecontrol` (220K), and `hcm-correctness-build` (3.9 MB).
- All superseded `/tmp/homecontrol-*.tar.gz` release archives, including the 21 MB `homecontrol-release-84f9f3...tar.gz` and the listed prior SHA archives.
- Obsolete rollback containers and images for releases `5f1228e`, `84f9f3`, `b1ef32`, `bd549f`, `c48f2e`, `db51246`, and `ec3fa9`.
- Temporary restore/debug probes (`/tmp/hcm-debug.env`, `/tmp/hcm-restore-pg.log`, `/tmp/conflict-status`).

Unrelated services, PostgreSQL storage, credentials, certificates, Heartbeat,
watchdog, and the retained rollback/recovery artifacts were preserved.
