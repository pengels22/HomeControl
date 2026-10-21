-- Configuration is non-secret JSON; secret material is encrypted separately.
ALTER TABLE integration_providers ADD COLUMN IF NOT EXISTS config_schema JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE integration_providers ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE integration_providers ADD COLUMN IF NOT EXISTS credential_ref UUID;
ALTER TABLE integration_providers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE integration_providers ADD COLUMN IF NOT EXISTS config_flow JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS integration_credentials (
    credential_ref UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id TEXT NOT NULL REFERENCES integration_providers(provider_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('api_key','username_password','oauth_access_token','oauth_refresh_token','client_secret','webhook_secret')),
    ciphertext BYTEA NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
DO $$ BEGIN
    ALTER TABLE integration_providers ADD CONSTRAINT integration_provider_credential_fk
        FOREIGN KEY (credential_ref) REFERENCES integration_credentials(credential_ref) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS integration_credentials_provider_idx ON integration_credentials(provider_id);

CREATE TABLE IF NOT EXISTS integration_oauth_states (
    state_hash TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES integration_providers(provider_id) ON DELETE CASCADE,
    redirect_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);
