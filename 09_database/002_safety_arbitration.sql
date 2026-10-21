-- Phase 3 additive safety-arbitration audit table.
-- Do not run on production until Phase 3 deployment is approved.

CREATE TABLE IF NOT EXISTS output_arbitration_events (
    id BIGSERIAL PRIMARY KEY,
    logical_device_id BIGINT REFERENCES logical_devices(id),
    device_id TEXT CHECK (
        device_id IS NULL OR (
            device_id ~ '^[0-9a-f]{12}$'
            AND device_id <> '000000000000'
            AND device_id <> 'ffffffffffff'
            AND device_id !~ '^[0-9a-f][13579bdf]'
        )
    ),
    channel_id TEXT NOT NULL,
    control_source TEXT NOT NULL,
    requested_state JSONB NOT NULL,
    effective_state JSONB NOT NULL,
    feedback_state JSONB,
    active_safety_conditions TEXT[] NOT NULL DEFAULT '{}',
    fault_state TEXT,
    inhibited BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_output_arbitration_events_created
    ON output_arbitration_events(created_at);

CREATE INDEX IF NOT EXISTS idx_output_arbitration_events_device_channel
    ON output_arbitration_events(device_id, channel_id);
