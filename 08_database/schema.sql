CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS modules (
    id BIGSERIAL PRIMARY KEY,
    module_uuid UUID UNIQUE NOT NULL,
    module_type TEXT NOT NULL CHECK (module_type IN ('RCM','LCM','SIM','PNL')),
    hostname TEXT UNIQUE NOT NULL,
    ip_address INET UNIQUE NOT NULL,
    hardware_revision TEXT,
    software_version TEXT,
    config_version INTEGER NOT NULL DEFAULT 0,
    online BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen TIMESTAMPTZ,
    last_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    commissioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rooms (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    floor TEXT,
    permanently_open_hvac BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS logical_devices (
    id BIGSERIAL PRIMARY KEY,
    logical_name TEXT UNIQUE NOT NULL,
    room_id BIGINT REFERENCES rooms(id),
    device_class TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    maintenance_locked BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS output_intents (
    id BIGSERIAL PRIMARY KEY,
    logical_device_id BIGINT NOT NULL REFERENCES logical_devices(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('life_safety','local_override','user','rules')),
    command JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    UNIQUE(logical_device_id, source)
);

CREATE TABLE IF NOT EXISTS device_bindings (
    id BIGSERIAL PRIMARY KEY,
    logical_device_id BIGINT NOT NULL REFERENCES logical_devices(id) ON DELETE CASCADE,
    module_id BIGINT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    channel TEXT,
    binding_type TEXT NOT NULL DEFAULT 'primary',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(logical_device_id,module_id,channel,binding_type)
);

CREATE TABLE IF NOT EXISTS hvac_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    mode TEXT NOT NULL DEFAULT 'OFF' CHECK (mode IN ('OFF','HEAT','COOL','FAN')),
    setpoint_f NUMERIC NOT NULL DEFAULT 70.0 CHECK (setpoint_f >= 45 AND setpoint_f <= 90),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS room_hvac (
    room_id BIGINT PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
    temperature_f NUMERIC,
    occupied BOOLEAN NOT NULL DEFAULT FALSE,
    actuated_damper BOOLEAN NOT NULL DEFAULT TRUE,
    damper_logical_device_id BIGINT REFERENCES logical_devices(id),
    sensor_ok BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS faults (
    id BIGSERIAL PRIMARY KEY,
    module_uuid UUID,
    logical_device_id BIGINT REFERENCES logical_devices(id),
    code TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN','READONLY')),
    password_hash TEXT,
    passkey_credential JSONB,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_challenges (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    challenge TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN','READONLY')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pairing_keys (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('HCM_SCREEN','PNL','RCM','LCM','SIM','RMC','OTHER')),
    pairing_token_hash TEXT UNIQUE NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    used_by TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS rules (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenes (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    definition JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS configuration_history (
    id BIGSERIAL PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    configuration JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS safety_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_modules_online ON modules(online);
CREATE INDEX IF NOT EXISTS idx_faults_active ON faults(active, severity);
CREATE INDEX IF NOT EXISTS idx_output_intents_active ON output_intents(logical_device_id, active, source);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(token_hash) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_auth_challenges_challenge ON auth_challenges(challenge) WHERE consumed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_pairing_keys_hash ON pairing_keys(pairing_token_hash) WHERE used_at IS NULL;

CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('normal','critical')),
    category TEXT NOT NULL DEFAULT 'general',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ
);
