-- HCM location hierarchy. ACM alarm Areas remain independent firmware data.
CREATE TABLE hcm_areas (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    enabled BOOLEAN NOT NULL DEFAULT true
);

ALTER TABLE rooms ADD COLUMN area_id BIGINT REFERENCES hcm_areas(id) ON DELETE RESTRICT;

CREATE TRIGGER area_registry_changed AFTER INSERT OR UPDATE OR DELETE ON hcm_areas
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
