-- Production PNL registration, delivery, commands, occupancy, and Sonic audit.
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS friendly_id TEXT;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS hostname TEXT;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS software_version TEXT;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS token_generation BIGINT NOT NULL DEFAULT 1;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS last_sonic_epoch BIGINT;
ALTER TABLE pnl_devices ADD COLUMN IF NOT EXISTS last_sonic_muted BOOLEAN;
CREATE UNIQUE INDEX IF NOT EXISTS pnl_devices_friendly_id_uq ON pnl_devices(friendly_id) WHERE friendly_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS pnl_credentials_audit (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    token_generation BIGINT NOT NULL,
    token_hash TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS pnl_credentials_audit_device_idx ON pnl_credentials_audit(device_id, token_generation DESC);

CREATE TABLE IF NOT EXISTS pnl_command_ledger (
    device_id TEXT NOT NULL REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    logical_entity TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted','rejected','pending','confirmed','failed','duplicate','expired')),
    response JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(device_id, request_id)
);
CREATE INDEX IF NOT EXISTS pnl_command_ledger_expiry_idx ON pnl_command_ledger(expires_at);

CREATE TABLE IF NOT EXISTS pnl_occupancy_events (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    occupied BOOLEAN,
    event_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(device_id, event_key),
    UNIQUE(device_id, sequence)
);

CREATE TABLE IF NOT EXISTS pnl_state_events (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES pnl_devices(device_id) ON DELETE CASCADE,
    sequence BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pnl_state_events_device_idx ON pnl_state_events(device_id, sequence);

CREATE UNIQUE INDEX IF NOT EXISTS dashboard_assignment_panel_primary_uq
    ON dashboard_assignments(pnl_device_id) WHERE pnl_device_id IS NOT NULL AND is_primary;
CREATE UNIQUE INDEX IF NOT EXISTS dashboard_assignment_area_primary_uq
    ON dashboard_assignments(area_id) WHERE area_id IS NOT NULL AND is_primary;
ALTER TABLE dashboard_assignments ADD CONSTRAINT dashboard_assignment_target_ck
    CHECK ((pnl_device_id IS NOT NULL) <> (area_id IS NOT NULL)) NOT VALID;
