# Remaining Open Items

Architecture is largely pinned.

Items intentionally deferred:
- exact configuration-file schemas
- exact PostgreSQL schema and migrations
- final notification repeat/escalation policy
- future remote-access implementation
- final per-circuit fuse sizing
- final build drawings / conduit schedules / terminal schedules
- final manufacturer BOM quantities and revision control

## Jetson deployment follow-up (2026-10-10)

The initial Jetson Docker/PostgreSQL/Heartbeat deployment and reboot validation are complete; refer to [the deployment runbook](JETSON_HCM_DEPLOYMENT_2026-10-10.md). Remaining: continuous crash recovery, secure admin credentials and HTTPS, USB backup and restore testing, stable authorized-client routing, and hardware safety commissioning. The existing dashboard does not establish production readiness.
