-- PNL backplane identity, telemetry, and global Sonic policy.
CREATE TABLE IF NOT EXISTS pnl_devices (
    device_id TEXT PRIMARY KEY CHECK (device_id ~ '^[0-9a-f]{12}$'),
    module_id BIGINT REFERENCES modules(id) ON DELETE SET NULL,
    area_id BIGINT REFERENCES hcm_areas(id) ON DELETE SET NULL,
    token_hash TEXT UNIQUE NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_sequence BIGINT NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    last_telemetry_at TIMESTAMPTZ,
    local_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    dashboard_revision TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pnl_telemetry_events (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    UNIQUE(device_id, sequence)
);

CREATE TABLE IF NOT EXISTS sonic_policy (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    epoch BIGINT NOT NULL DEFAULT 1 CHECK (epoch > 0),
    globally_muted BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO sonic_policy(singleton, epoch, globally_muted)
VALUES (TRUE, 1, TRUE)
ON CONFLICT (singleton) DO NOTHING;
