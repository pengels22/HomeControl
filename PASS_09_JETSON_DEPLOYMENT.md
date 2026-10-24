# Pass 9 Jetson deployment

## Preflight

Repository baseline was `aaac188`; the Pass 9 software work is prepared locally.
The documented host is `192.168.20.27`, with HCM in `hcm-test`, PostgreSQL in
`hcm-postgres`, persistent HCM data under `/srv/hcm-data/homecontrol`, and
independent Heartbeat V3/watchdog services.

The read-only SSH preflight was attempted with a five-second timeout and failed
authentication (`Permission denied (publickey,password)`). Consequently, live
Docker health, disk, migration status, backups, container SHA, watchdog status,
and module dependencies could not be inspected from this session.

## Change gate

No PostgreSQL backup, live migration, container replacement, service restart,
network change, or physical output operation was performed. The required
approval checkpoint remains pending because backup/restore verification and
current host state are unavailable. Heartbeat V3 was not touched.

## Deployment procedure when access and approval are available

1. Run the documented read-only Jetson checks in `JETSON_OPERATIONS.md`.
2. Create and restore-test a host-local PostgreSQL backup; record current SHA and
   migration level.
3. Run `homecontrol-db status`, review pending migration 029, then use the
   supported deployment framework with the exact Pass 9 SHA and rollback point.
4. Verify `/api/v1/version`, authentication, `/pnl`, `/editor`, PNL panel auth,
   dashboard retrieval, Sonic policy, watchdog, and Heartbeat V3 without
   exercising physical outputs.

The deployment adapter must preserve private Docker networking, USB storage,
certificates, secrets, host Heartbeat V3, and the HCM-only watchdog.
