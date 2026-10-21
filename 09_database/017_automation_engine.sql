CREATE TABLE IF NOT EXISTS automations (
    automation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    mode TEXT NOT NULL DEFAULT 'single' CHECK (mode IN ('single','restart','queued','parallel')),
    max_runs SMALLINT NOT NULL DEFAULT 10 CHECK (max_runs BETWEEN 1 AND 10),
    trigger_definitions JSONB NOT NULL CHECK (jsonb_typeof(trigger_definitions)='array'),
    condition_definition JSONB,
    action_sequence JSONB NOT NULL CHECK (jsonb_typeof(action_sequence)='array'),
    revision INTEGER NOT NULL DEFAULT 1,
    validation_status TEXT NOT NULL DEFAULT 'valid',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_triggered_at TIMESTAMPTZ,
    last_run_status TEXT
);
CREATE INDEX IF NOT EXISTS automations_enabled_idx ON automations(enabled);

CREATE TABLE IF NOT EXISTS automation_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_id UUID NOT NULL REFERENCES automations(automation_id) ON DELETE CASCADE,
    trigger_source TEXT NOT NULL,
    trigger_event_id BIGINT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running','success','failed','cancelled','skipped','HCM_RESTART')),
    result TEXT,
    error_category TEXT,
    mode TEXT NOT NULL,
    trace JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(trace)='array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS automation_runs_automation_idx ON automation_runs(automation_id,started_at DESC);
CREATE INDEX IF NOT EXISTS automation_runs_event_idx ON automation_runs(trigger_event_id);

CREATE TABLE IF NOT EXISTS automation_engine_state (
    state_key TEXT PRIMARY KEY,
    last_event_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO automation_engine_state(state_key,last_event_id) VALUES('integration_events',0) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS automation_schedule_ledger (
    occurrence_id BIGSERIAL PRIMARY KEY,
    automation_id UUID NOT NULL REFERENCES automations(automation_id) ON DELETE CASCADE,
    trigger_key TEXT NOT NULL,
    intended_fire_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('scheduled','executed','caught_up','skipped')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(automation_id,trigger_key,intended_fire_at)
);
CREATE INDEX IF NOT EXISTS automation_schedule_due_idx ON automation_schedule_ledger(status,intended_fire_at);
