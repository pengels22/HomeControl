ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS sync_state JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS account_ref UUID REFERENCES integration_credentials(credential_ref) ON DELETE SET NULL;
