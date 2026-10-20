CREATE TABLE IF NOT EXISTS notification_destinations (
    destination_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    destination_type TEXT NOT NULL CHECK (destination_type ~ '^[a-z][a-z0-9_]{0,63}$'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    configured BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'unconfigured' CHECK (status IN ('unconfigured','configured','healthy','credential_missing','backend_unavailable','error')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config)='object'),
    credential_ref UUID REFERENCES integration_credentials(credential_ref) ON DELETE SET NULL,
    last_success TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS speech_backends (
    backend_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    backend_type TEXT NOT NULL CHECK (backend_type ~ '^[a-z][a-z0-9_]{0,63}$'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    configured BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'unconfigured' CHECK (status IN ('unconfigured','configured','healthy','credential_missing','backend_unavailable','error')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config)='object'),
    credential_ref UUID REFERENCES integration_credentials(credential_ref) ON DELETE SET NULL,
    languages JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(languages)='array'),
    voices JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(voices)='array'),
    last_success TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notification_source_mappings (
    source_service TEXT PRIMARY KEY,
    destination_id UUID NOT NULL REFERENCES notification_destinations(destination_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS speech_source_mappings (
    source_entity TEXT PRIMARY KEY,
    backend_id UUID NOT NULL REFERENCES speech_backends(backend_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notification_destinations_status_idx ON notification_destinations(status,enabled);
CREATE INDEX IF NOT EXISTS speech_backends_status_idx ON speech_backends(status,enabled);
