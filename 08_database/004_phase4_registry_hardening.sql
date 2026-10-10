-- Phase 4 registry hardening.
-- Do not run on the live database without an approved maintenance window.
-- These indexes close PostgreSQL NULL uniqueness gaps and prevent conflicting
-- active physical assignments. Management APIs also validate capabilities and
-- channel support before inserting or updating bindings.

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_bindings_active_channel_unique
    ON device_bindings(module_id, channel)
    WHERE enabled = true AND channel IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_bindings_active_null_channel_unique
    ON device_bindings(module_id, binding_type)
    WHERE enabled = true AND channel IS NULL;
