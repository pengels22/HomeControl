ALTER TABLE integration_instances DROP CONSTRAINT IF EXISTS integration_instances_status_check;
ALTER TABLE integration_instances ADD CONSTRAINT integration_instances_status_check CHECK (status IN
    ('connected','disabled','configuration_required','authentication_required','degraded','disconnected','error','provider_missing'));
