-- HCM-controlled module operational role switching.
-- Additive only. Do not run on the live database without an approved
-- maintenance window, backup, and rollback plan.

CREATE TABLE IF NOT EXISTS module_role_transitions (
    operation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id BIGINT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL CHECK (
        device_id ~ '^[0-9a-f]{12}$'
        AND device_id <> '000000000000'
        AND device_id <> 'ffffffffffff'
        AND device_id !~ '^[0-9a-f][13579bdf]'
    ),
    actor TEXT NOT NULL,
    previous_role TEXT NOT NULL CHECK (previous_role IN ('UNASSIGNED','RCM','SIM','LCM')),
    requested_role TEXT NOT NULL CHECK (requested_role IN ('UNASSIGNED','RCM','SIM','LCM')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','SENT','ACCEPTED','APPLYING','CONFIRMED','REJECTED','TIMED_OUT','FAILED')),
    simulation_required BOOLEAN NOT NULL DEFAULT TRUE,
    control_session_key TEXT NOT NULL,
    command_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ack_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    rejection_reason TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_module_role_transitions_device_requested
    ON module_role_transitions(device_id, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_module_role_transitions_status_expires
    ON module_role_transitions(status, expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_module_role_transitions_active_device
    ON module_role_transitions(device_id)
    WHERE status IN ('PENDING','SENT','ACCEPTED','APPLYING');
