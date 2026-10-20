ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS last_attempt TIMESTAMPTZ;
ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS last_successful_poll TIMESTAMPTZ;
ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS backoff_until TIMESTAMPTZ;
ALTER TABLE integration_instances ADD COLUMN IF NOT EXISTS stale BOOLEAN NOT NULL DEFAULT false;
