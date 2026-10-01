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
    passkey_credential JSONB,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
