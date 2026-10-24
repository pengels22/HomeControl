# Pass 9 Jetson deployment

## Preflight

Repository baseline is `21079a9`; the Pass 9 software work is prepared and
pushed to `origin/main`.
The documented host is `192.168.20.27`, with HCM in `hcm-test`, PostgreSQL in
`hcm-postgres`, persistent HCM data under `/srv/hcm-data/homecontrol`, and
independent Heartbeat V3/watchdog services.

The read-only SSH preflight now succeeds through the configured `jetson` alias.
Docker, PostgreSQL, HCM, Heartbeat V3, and the watchdog timer are active. HCM
reports HTTP 200 health and the deployed version endpoint identifies container
SHA `c48f2e7991e16b2eb5fb9428fcbf815f9b8102ce`. Heartbeat V3 reports Jetson
`192.168.20.27`, Conflict `192.168.20.26` online, and an operational state.
The route is Ethernet-first on `eth0`; `/srv/hcm-data` has approximately 14 GB
available. Before deployment, a fresh backup was created at
`/srv/hcm-data/backups/homecontrol-20261024T132040Z-pre-pass9.dump` (242394
bytes) and restored successfully into an isolated PostgreSQL 16 container.

## Change gate

With explicit approval, migrations 026–029 were applied and the supported Docker
replacement completed under deployment ID `hc-20261024T1330Z-84f9f3f3`. HCM now
runs image `homecontrol-hcm:84f9f3f340bb0fd47108245546fbf121c267d4dd`; the prior
image is preserved as `hcm-rollback-hc-20261024T1330Z-84f9f3f3`. PostgreSQL,
Heartbeat V3, and the HCM-only watchdog were preserved.

Post-deployment checks passed: version and health, unauthenticated 401 checks
for PNL/editor routes, mounted PKI/data/Matter/safety paths, watchdog health,
Heartbeat V3 operational state, and Conflict online status. No physical output
operation was performed.

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
