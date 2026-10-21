-- Persisted, non-executable Home Assistant migration workspace.
CREATE TABLE IF NOT EXISTS ha_migration_items (
    staged_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system TEXT NOT NULL DEFAULT 'home_assistant' CHECK (source_system ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('automation','script','scene')),
    source_identifier TEXT NOT NULL CHECK (length(source_identifier) BETWEEN 1 AND 512),
    source_name TEXT NOT NULL CHECK (length(source_name) BETWEEN 1 AND 512),
    source_document JSONB NOT NULL,
    source_fingerprint TEXT NOT NULL,
    source_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    state_provenance TEXT NOT NULL DEFAULT 'IMPORT_DEFAULT_ENABLED' CHECK (state_provenance IN ('HA_RUNTIME_STATE','HA_INITIAL_STATE','IMPORT_DEFAULT_ENABLED')),
    compatibility_status TEXT NOT NULL CHECK (compatibility_status IN ('READY','READY_WITH_TRANSLATIONS','BLOCKED_MAPPING','BLOCKED_SERVICE','BLOCKED_UNSUPPORTED')),
    compatibility_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    native_preview JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_native_ref TEXT,
    source_revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_system, source_kind, source_identifier)
);
CREATE INDEX IF NOT EXISTS ha_migration_items_list_idx ON ha_migration_items(source_system, source_kind, source_name);
CREATE INDEX IF NOT EXISTS ha_migration_items_status_idx ON ha_migration_items(compatibility_status, source_enabled);
