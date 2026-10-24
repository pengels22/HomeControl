# Pass 8 database changes

Migration `029_pnl_production_integration.sql` is additive. It extends
`pnl_devices` with friendly identity, hostname, software version, credential
generation, revocation, heartbeat, and Sonic acknowledgement fields. It adds
credential audit, bounded command ledger, occupancy event, and state event
tables. Partial unique indexes enforce one primary panel and one primary area
dashboard assignment.

Telemetry remains append-only under the existing `pnl_telemetry_events` table.
The command/event delivery surfaces are bounded by request TTL and a 100-event
response limit; deployments should schedule retention of expired telemetry and
ledger rows under their existing PostgreSQL backup policy. No historical rows
are deleted by this migration.

Rollback requires a PostgreSQL backup and a controlled reverse migration after
confirming no panel is using generation or event columns. Live migrations were
not run in this pass.
