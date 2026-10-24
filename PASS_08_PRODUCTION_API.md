# Pass 8 production API

## Authentication

Administrative routes use the existing HCM bearer session and require `ADMIN`.
Panel routes use `Authorization: Bearer <per-panel-token>` plus
`X-PNL-Device: <normalized MAC>`. Tokens are generated independently per panel,
stored only as SHA-256 hashes, and are never listed.

## Administration

- `POST /api/v1/pnl-production/admin/devices` registers a panel and returns its token once.
- `GET /api/v1/pnl-production/admin/devices` lists status without credentials.
- `PATCH /api/v1/pnl-production/admin/devices/{device_id}` changes friendly name, hostname, area, version, or enabled state.
- `POST /api/v1/pnl-production/admin/devices/{device_id}/rotate-credentials` revokes the old generation and returns the new token once.
- `POST /api/v1/pnl-production/admin/devices/{device_id}/revoke` disables and revokes the panel.
- `POST /api/v1/pnl-production/admin/dashboard-assignments` assigns a published dashboard to exactly one panel or area.
- `GET/PUT /api/v1/pnl-production/admin/sonic-policy` inspects or advances the global microphone policy epoch.

## Panel routes

- `GET /panel/config` returns published dashboard, SHA, revision, area, and authorized catalog. `If-None-Match` with the SHA returns `304`.
- `GET /panel/state` returns an initial authorized snapshot.
- `GET /panel/events?since=N` returns at most 100 ordered events for resynchronization.
- `POST /panel/commands` accepts button, slider, entity, and thermostat requests with a request ID and bounded TTL.
- `POST /panel/occupancy` accepts ordered immediate occupancy events with a deduplication key.
- `POST /panel/heartbeat` records contact while retaining Unified Heartbeat V3 semantics.
- `GET /panel/sonic-policy` and `POST /panel/sonic-ack` deliver and acknowledge policy epochs.

Commands return accepted, failed, duplicate, or unavailable results and never
claim physical success merely because HCM accepted a request.
