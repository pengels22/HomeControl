CREATE TABLE IF NOT EXISTS dashboard_documents (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    scope TEXT NOT NULL DEFAULT 'shared' CHECK (scope IN ('shared','panel','area')),
    owner TEXT NOT NULL,
    draft_revision BIGINT NOT NULL DEFAULT 0,
    published_revision BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dashboard_revisions (
    id BIGSERIAL PRIMARY KEY,
    dashboard_id BIGINT NOT NULL REFERENCES dashboard_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL CHECK (revision > 0),
    layout JSONB NOT NULL,
    layout_sha256 TEXT NOT NULL CHECK (layout_sha256 ~ '^[0-9a-f]{64}$'),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(dashboard_id, revision)
);

CREATE TABLE IF NOT EXISTS dashboard_assignments (
    id BIGSERIAL PRIMARY KEY,
    dashboard_id BIGINT NOT NULL REFERENCES dashboard_documents(id) ON DELETE CASCADE,
    pnl_device_id TEXT REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    area_id BIGINT REFERENCES hcm_areas(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(dashboard_id, pnl_device_id, area_id)
);
