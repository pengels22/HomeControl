-- Additive cleanup for authenticated login/session and output intent contracts.
-- Historical migrations remain immutable.

ALTER TABLE output_intents DROP CONSTRAINT IF EXISTS output_intents_source_check;
ALTER TABLE output_intents
    ADD CONSTRAINT output_intents_source_check
    CHECK (source IN ('life_safety','local_override','user','rules','schedule','scene'));

CREATE TABLE IF NOT EXISTS auth_login_rate_limits (
    scope TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    next_allowed_at TIMESTAMPTZ,
    last_failed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_active_user
    ON user_sessions(username, expires_at) WHERE revoked_at IS NULL;
