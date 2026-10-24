# HCM integration foundation

This is the first backend slice. Only an internal mock provider is implemented.
There are no third-party connections, credentials, OAuth flows, public action
execution routes, or new physical control paths.

## Persistence and identity

Apply `09_database/009_integration_foundation.sql` through the existing reviewed
migration procedure before running this HCM version. Startup checks the schema;
it does not apply migrations. Back up the database before an approved deployment.
No live deployment is authorized by this document.

The migration adds `integration_providers`, `entities`, and `service_definitions`.
Devices reuse `logical_devices`, with nullable provider ownership and external
identity columns. Native rows retain their identities, mappings, maintenance
settings, and room assignments. Entities reference their owning provider's device
through a composite foreign key.

Provider IDs and external IDs identify records; display names do not. Repeating
registration preserves numeric IDs and existing room assignments unless a room
is explicitly supplied. Entity IDs use `domain.name`; implicit reassignment to a
different entity ID or device is rejected. State, attributes, availability,
last-update time, and last-value-change time are persisted separately.

## Lifecycle and services

`02_HCM/integrations/provider.py` defines setup, start, stop, reload, health check,
and diagnostics. The runtime isolates asynchronous provider exceptions and
timeouts, records sanitized error summaries, and checks health every 30 seconds.
Providers must remain cooperative asynchronous code; this is not process
isolation for blocking or untrusted plugins.

Provider registration persists enabled/configured flags from runtime attachment.
This slice has no configuration editing API. Restart, stop, and unhealthy status
mark owned resources unavailable without deleting their identities or last
states. Successful health checks update last success; providers must refresh
resource availability/state after recovery.

Service declarations persist domain, name, provider, JSON argument schema, target
requirements, and whether they mutate physical state. Handlers are process-local.
The internal dispatcher validates arguments and provider/target availability and
ownership. Physical services are rejected in this slice. No automation executor
or physical output adapter is connected to this dispatcher.

## Events

`02_HCM/events.py` uses the existing `EventRecord` model. Provider events carry
provider/device/entity identity, origin, correlation ID, and payload. State
reports publish `entity.state_changed` after a successful database write
(including repeated samples; `last_changed` tracks value changes only).
Custom events require the provider's namespace.

Subscriptions are bounded in-process queues with independent copies. Slow
consumers lose their oldest queued event and receive a dropped-event count.
This is best-effort delivery, not a durable outbox or automation execution queue.
Routine telemetry does not append administrative device-management audit rows.

## Authenticated inspection

All routes use the existing HCM user authentication, including READONLY access:

- `GET /api/v1/integrations`
- `GET /api/v1/integrations/devices`
- `GET /api/v1/integrations/entities`
- `GET /api/v1/integrations/services`
- `GET /api/v1/integrations/{provider_id}/status`
- `GET /api/v1/integrations/{provider_id}/diagnostics`

Devices, entities, and services support an optional `provider_id` query filter.
Diagnostics expose typed counters and checks, not arbitrary exception messages
or configuration. Inspection covers provider-owned resources; existing native
device inspection remains in its existing API.

## Internal mock and validation

`internal_mock` is registered but disabled by default. In a local test
environment, `HCM_INTEGRATION_MOCK_ENABLED=true` enables one device, one
temperature sensor, a startup event, and a harmless `internal_mock.ping` service.
The provider's `update(value)` and `fail_health` test hooks exercise state changes
and health failure. Nothing binds it to physical channels.

`12_tests/test_integration_foundation.py` exercises PostgreSQL persistence,
forward/repeated migration preservation, stable identity, ownership, lifecycle
failure, service validation, event backpressure, and authenticated inspection.
Set `HCM_TEST_DATABASE_URL` to a disposable PostgreSQL database to run these tests.
They use isolated temporary schemas and require no external credentials.

Real providers, provider configuration UI, credentials/OAuth, durable event
delivery, automation consumption, and authorized physical action adapters remain
future work. Existing life-safety, HVAC, heartbeat, commissioning, and module
mapping behavior are outside this foundation.
