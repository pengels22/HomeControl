-- Provider records supplement native module/channel registries; no output mappings change.
CREATE TABLE IF NOT EXISTS integration_providers (
    provider_id TEXT PRIMARY KEY CHECK (provider_id ~ '^[a-z][a-z0-9_]{0,63}$'),
    display_name TEXT NOT NULL,
    version TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT false,
    configured BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'disabled' CHECK (status IN
        ('disabled','configuration_required','starting','connected','degraded','stopped','error')),
    last_success TIMESTAMPTZ,
    last_error TEXT,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(capabilities)='object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reuse HCM logical identity and rooms. Native logical devices retain NULL ownership.
ALTER TABLE logical_devices ADD COLUMN IF NOT EXISTS provider_id TEXT REFERENCES integration_providers(provider_id);
ALTER TABLE logical_devices ADD COLUMN IF NOT EXISTS external_device_id TEXT;
ALTER TABLE logical_devices ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE logical_devices ADD COLUMN IF NOT EXISTS availability TEXT NOT NULL DEFAULT 'unknown';
CREATE UNIQUE INDEX IF NOT EXISTS logical_devices_provider_external ON logical_devices(provider_id,external_device_id);
CREATE UNIQUE INDEX IF NOT EXISTS logical_devices_provider_identity ON logical_devices(provider_id,id);

CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    entity_id TEXT UNIQUE NOT NULL CHECK (entity_id ~ '^[a-z][a-z0-9_]*\.[a-z0-9_]+$'),
    domain TEXT NOT NULL CHECK (domain ~ '^[a-z][a-z0-9_]*$'),
    provider_id TEXT NOT NULL REFERENCES integration_providers(provider_id),
    external_entity_id TEXT NOT NULL,
    device_id BIGINT NOT NULL,
    display_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    available BOOLEAN NOT NULL DEFAULT false,
    state JSONB,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(attributes)='object'),
    unit TEXT,
    device_class TEXT,
    last_updated TIMESTAMPTZ,
    last_changed TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider_id,external_entity_id),
    FOREIGN KEY(provider_id,device_id) REFERENCES logical_devices(provider_id,id),
    CHECK (split_part(entity_id,'.',1)=domain)
);

CREATE TABLE IF NOT EXISTS service_definitions (
    provider_id TEXT NOT NULL REFERENCES integration_providers(provider_id),
    domain TEXT NOT NULL CHECK (domain ~ '^[a-z][a-z0-9_]*$'),
    service_name TEXT NOT NULL CHECK (service_name ~ '^[a-z][a-z0-9_]*$'),
    argument_schema JSONB NOT NULL CHECK (jsonb_typeof(argument_schema)='object'),
    target_requirements JSONB NOT NULL CHECK (jsonb_typeof(target_requirements)='object'),
    mutates_physical_state BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY(provider_id,domain,service_name)
);
