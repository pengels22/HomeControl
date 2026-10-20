-- Instance ownership is additive; NULL retains legacy provider-level ownership.
ALTER TABLE entities ADD COLUMN IF NOT EXISTS instance_id UUID REFERENCES integration_instances(instance_id) ON DELETE SET NULL;
ALTER TABLE service_definitions ADD COLUMN IF NOT EXISTS instance_id UUID REFERENCES integration_instances(instance_id) ON DELETE CASCADE;
DROP INDEX IF EXISTS logical_devices_provider_external;
CREATE UNIQUE INDEX IF NOT EXISTS logical_devices_instance_external ON logical_devices(provider_id,COALESCE(instance_id,'00000000-0000-0000-0000-000000000000'::uuid),external_device_id);
DROP INDEX IF EXISTS entities_provider_external_entity_id_key;
ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_provider_id_external_entity_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS entities_instance_external ON entities(provider_id,COALESCE(instance_id,'00000000-0000-0000-0000-000000000000'::uuid),external_entity_id);
CREATE INDEX IF NOT EXISTS entities_instance_idx ON entities(instance_id);
CREATE INDEX IF NOT EXISTS service_definitions_instance_idx ON service_definitions(instance_id);
