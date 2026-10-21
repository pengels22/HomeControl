ALTER TABLE automation_schedule_ledger ADD COLUMN IF NOT EXISTS trigger_id TEXT;
ALTER TABLE automation_schedule_ledger ADD COLUMN IF NOT EXISTS actual_fire_at TIMESTAMPTZ;
ALTER TABLE automation_schedule_ledger ADD COLUMN IF NOT EXISTS catch_up BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE automation_schedule_ledger ADD COLUMN IF NOT EXISTS reason TEXT;
UPDATE automation_schedule_ledger SET trigger_id=trigger_key WHERE trigger_id IS NULL;
ALTER TABLE automation_schedule_ledger ALTER COLUMN trigger_id SET NOT NULL;
DROP INDEX IF EXISTS automation_schedule_ledger_automation_id_trigger_key_intended_fire_at_key;
CREATE UNIQUE INDEX IF NOT EXISTS automation_schedule_occurrence_identity ON automation_schedule_ledger(automation_id,trigger_id,intended_fire_at);
CREATE TABLE IF NOT EXISTS automation_scheduler_state (
    state_key TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO automation_scheduler_state(state_key,last_seen_at) VALUES('scheduler',now()) ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS automation_schedule_trigger_idx ON automation_schedule_ledger(automation_id,trigger_id,intended_fire_at DESC);
