-- Generic external-source to immutable HCM identity mappings.
CREATE TABLE IF NOT EXISTS migration_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system TEXT NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_kind TEXT NOT NULL CHECK (source_kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_identifier TEXT NOT NULL CHECK (length(source_identifier) BETWEEN 1 AND 512),
    source_subidentifier TEXT,
    source_fingerprint TEXT,
    target_kind TEXT NOT NULL CHECK (target_kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    target_ref TEXT NOT NULL CHECK (length(target_ref) BETWEEN 1 AND 256),
    status TEXT NOT NULL DEFAULT 'VALID' CHECK (status IN ('VALID','TARGET_MISSING','SOURCE_CHANGED','AMBIGUOUS','UNCONFIRMED','INVALID')),
    confidence TEXT NOT NULL DEFAULT 'EXACT' CHECK (confidence IN ('EXACT','SUGGESTED','AMBIGUOUS','UNRESOLVED')),
    origin TEXT NOT NULL DEFAULT 'USER_CONFIRMED' CHECK (origin IN ('EXACT_AUTOMATIC','USER_CONFIRMED','IMPORT_PLANNED','MIGRATED','SYSTEM')),
    notes TEXT,
    actor TEXT,
    last_validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS migration_mappings_source_unique
    ON migration_mappings(source_system,source_kind,source_identifier,COALESCE(source_subidentifier,''));
CREATE INDEX IF NOT EXISTS migration_mappings_target_idx ON migration_mappings(target_kind,target_ref);
CREATE INDEX IF NOT EXISTS migration_mappings_status_idx ON migration_mappings(status,confidence);
CREATE TABLE IF NOT EXISTS migration_mapping_aliases (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_id UUID NOT NULL REFERENCES migration_mappings(mapping_id) ON DELETE CASCADE,
    source_system TEXT NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_kind TEXT NOT NULL CHECK (source_kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    alias_identifier TEXT NOT NULL CHECK (length(alias_identifier) BETWEEN 1 AND 512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_system,source_kind,alias_identifier)
);
CREATE INDEX IF NOT EXISTS migration_mapping_aliases_mapping_idx ON migration_mapping_aliases(mapping_id);
