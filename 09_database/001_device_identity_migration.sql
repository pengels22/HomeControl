-- Phase 1 non-destructive migration from generated module_uuid to normalized
-- MAC-derived device_id. Do not drop module_uuid in this migration.
--
-- This migration is intentionally additive and repeat-safe. It adds the new
-- columns and constraints without backfilling from unreviewed data.

ALTER TABLE modules
    ADD COLUMN IF NOT EXISTS device_id TEXT,
    ADD COLUMN IF NOT EXISTS identity_interface TEXT,
    ADD COLUMN IF NOT EXISTS heartbeat_ip INET,
    ADD COLUMN IF NOT EXISTS control_session_online BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS supervision_state TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS supervision_last_seen TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS supervision_fresh_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_health JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE faults
    ADD COLUMN IF NOT EXISTS device_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'modules_device_id_format'
    ) THEN
        ALTER TABLE modules
            ADD CONSTRAINT modules_device_id_format
            CHECK (
                device_id IS NULL OR (
                    device_id ~ '^[0-9a-f]{12}$'
                    AND device_id <> '000000000000'
                    AND device_id <> 'ffffffffffff'
                    AND device_id !~ '^[0-9a-f][13579bdf]'
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'faults_device_id_format'
    ) THEN
        ALTER TABLE faults
            ADD CONSTRAINT faults_device_id_format
            CHECK (
                device_id IS NULL OR (
                    device_id ~ '^[0-9a-f]{12}$'
                    AND device_id <> '000000000000'
                    AND device_id <> 'ffffffffffff'
                    AND device_id !~ '^[0-9a-f][13579bdf]'
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'modules_supervision_state_valid'
    ) THEN
        ALTER TABLE modules
            ADD CONSTRAINT modules_supervision_state_valid
            CHECK (supervision_state IN ('unknown','online','degraded','fault','offline','stale','unavailable'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_modules_device_id_unique
    ON modules(device_id)
    WHERE device_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_faults_device_id
    ON faults(device_id)
    WHERE device_id IS NOT NULL;

-- Backfill must be performed from an operator-reviewed mapping of existing
-- module_uuid/hostname/IP to physical-interface MAC. Do not infer device_id
-- from IP or hostname alone.
