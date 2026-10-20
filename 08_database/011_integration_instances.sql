-- Provider definitions remain in integration_providers; configured identities are instances.
CREATE TABLE IF NOT EXISTS integration_instances (
    instance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id TEXT NOT NULL REFERENCES integration_providers(provider_id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT false,
    configured BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'configuration_required' CHECK (status IN ('connected','disabled','configuration_required','authentication_required','degraded','disconnected','error')),
    config_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    credential_ref UUID REFERENCES integration_credentials(credential_ref) ON DELETE SET NULL,
    last_success TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider_id,display_name)
);
ALTER TABLE logical_devices ADD COLUMN IF NOT EXISTS instance_id UUID REFERENCES integration_instances(instance_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS logical_devices_instance_idx ON logical_devices(instance_id);
ALTER TABLE integration_oauth_states ADD COLUMN IF NOT EXISTS instance_id UUID REFERENCES integration_instances(instance_id) ON DELETE CASCADE;
