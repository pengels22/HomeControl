-- Instance-safe service bindings and a bounded generic integration event log.
ALTER TABLE service_definitions DROP CONSTRAINT IF EXISTS service_definitions_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS service_definitions_instance_identity
    ON service_definitions(provider_id,COALESCE(instance_id,'00000000-0000-0000-0000-000000000000'::uuid),domain,service_name);

CREATE TABLE IF NOT EXISTS integration_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider_id TEXT,
    instance_id UUID,
    device_id BIGINT,
    entity_id BIGINT,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload)='object'),
    durability TEXT NOT NULL CHECK (durability IN ('DURABLE','COALESCED','BEST_EFFORT')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS integration_events_type_id_idx ON integration_events(event_type,event_id);
CREATE INDEX IF NOT EXISTS integration_events_created_idx ON integration_events(created_at);
