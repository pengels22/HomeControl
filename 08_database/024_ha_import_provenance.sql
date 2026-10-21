-- Durable provenance for native objects created by the HA importer.
ALTER TABLE automations ADD COLUMN IF NOT EXISTS source_system TEXT;
ALTER TABLE automations ADD COLUMN IF NOT EXISTS source_kind TEXT;
ALTER TABLE automations ADD COLUMN IF NOT EXISTS source_staged_id UUID;
ALTER TABLE automations ADD COLUMN IF NOT EXISTS source_identifier TEXT;
ALTER TABLE automations ADD COLUMN IF NOT EXISTS source_fingerprint TEXT;
ALTER TABLE automations ADD COLUMN IF NOT EXISTS imported_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS automations_ha_source_unique
    ON automations(source_system, source_kind, source_identifier)
    WHERE source_system IS NOT NULL AND source_kind IS NOT NULL AND source_identifier IS NOT NULL;
ALTER TABLE ha_migration_items ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'HA_STAGED';
ALTER TABLE ha_migration_items ADD COLUMN IF NOT EXISTS imported_at TIMESTAMPTZ;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ha_migration_items_lifecycle_status_check') THEN
        ALTER TABLE ha_migration_items ADD CONSTRAINT ha_migration_items_lifecycle_status_check
            CHECK (lifecycle_status IN ('HA_STAGED','HA_IMPORTED','HA_IMPORT_STALE'));
    END IF;
END $$;
