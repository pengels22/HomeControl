-- Phase 4 additive module registry foundation.
-- Do not run on the live database without an approved maintenance window.
-- This migration stores module capabilities separately from configuration,
-- operational state, and health, and adds an audit trail for management writes.

CREATE TABLE IF NOT EXISTS module_capabilities (
    id BIGSERIAL PRIMARY KEY,
    module_id BIGINT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    capability TEXT NOT NULL CHECK (capability ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$'),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(module_id, capability)
);

CREATE TABLE IF NOT EXISTS device_management_events (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    before_state JSONB,
    after_state JSONB,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_module_capabilities_module
    ON module_capabilities(module_id);

CREATE INDEX IF NOT EXISTS idx_module_capabilities_capability
    ON module_capabilities(capability);

CREATE INDEX IF NOT EXISTS idx_device_management_events_target
    ON device_management_events(target_type, target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_device_management_events_actor
    ON device_management_events(actor, created_at DESC);
