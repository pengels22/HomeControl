CREATE TABLE IF NOT EXISTS native_helpers (
    helper_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_ref BIGINT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE RESTRICT,
    entity_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    helper_type TEXT NOT NULL CHECK (helper_type IN ('input_boolean','input_button','input_number','input_text','input_select','input_datetime','counter','timer','schedule')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config)='object'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS native_helpers_type_idx ON native_helpers(helper_type,enabled);

CREATE TABLE IF NOT EXISTS native_scripts (
    script_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_ref BIGINT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE RESTRICT,
    entity_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    mode TEXT NOT NULL DEFAULT 'single' CHECK (mode IN ('single','restart','queued','parallel')),
    max_runs SMALLINT NOT NULL DEFAULT 10 CHECK (max_runs BETWEEN 1 AND 10),
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(input_schema)='object'),
    action_sequence JSONB NOT NULL CHECK (jsonb_typeof(action_sequence)='array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS native_scenes (
    scene_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_ref BIGINT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE RESTRICT,
    entity_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    targets JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(targets)='array'),
    snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS native_scenes_snapshot_idx ON native_scenes(snapshot,enabled);
ALTER TABLE automation_runs ALTER COLUMN automation_id DROP NOT NULL;
ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS script_id UUID REFERENCES native_scripts(script_id) ON DELETE CASCADE;
ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS run_kind TEXT NOT NULL DEFAULT 'automation' CHECK (run_kind IN ('automation','script'));
ALTER TABLE automation_runs DROP CONSTRAINT IF EXISTS automation_runs_owner_check;
ALTER TABLE automation_runs ADD CONSTRAINT automation_runs_owner_check CHECK ((run_kind='automation' AND automation_id IS NOT NULL AND script_id IS NULL) OR (run_kind='script' AND script_id IS NOT NULL AND automation_id IS NULL));
CREATE INDEX IF NOT EXISTS automation_runs_script_idx ON automation_runs(script_id,started_at DESC);
