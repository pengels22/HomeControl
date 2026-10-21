-- Additive touchscreen PIN authentication. Do not run without an approved
-- backup and migration window. PIN material never leaves HCM.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS touchscreen_pin_hash TEXT,
    ADD COLUMN IF NOT EXISTS touchscreen_pin_lookup TEXT,
    ADD COLUMN IF NOT EXISTS touchscreen_pin_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS touchscreen_permission TEXT NOT NULL DEFAULT 'VIEWER',
    ADD COLUMN IF NOT EXISTS touchscreen_pin_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS touchscreen_session_policy JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$ BEGIN
    ALTER TABLE users ADD CONSTRAINT users_touchscreen_permission_check
        CHECK (touchscreen_permission IN ('VIEWER','CONTROL','ADMIN'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_touchscreen_pin_lookup
    ON users(touchscreen_pin_lookup)
    WHERE touchscreen_pin_enabled = TRUE AND touchscreen_pin_lookup IS NOT NULL;

CREATE TABLE IF NOT EXISTS touchscreen_devices (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT UNIQUE NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    permitted_module_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS touchscreen_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id BIGINT NOT NULL REFERENCES touchscreen_devices(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('VIEWER','CONTROL','ADMIN')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    idle_expires_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoke_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_touchscreen_sessions_user_device
    ON touchscreen_sessions(user_id, device_id)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS touchscreen_rate_limits (
    scope TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    next_allowed_at TIMESTAMPTZ,
    last_failed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
