-- Additive: reuse rooms, preserve bindings, identities, authentication and HVAC.
CREATE TABLE channel_metadata (
    id BIGSERIAL PRIMARY KEY,
    module_id BIGINT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    channel_kind TEXT NOT NULL CHECK (channel_kind IN ('relay','lv_dimmer','hv_dimmer')),
    display_name TEXT NOT NULL DEFAULT '' CHECK (length(display_name)<=120),
    room_id BIGINT REFERENCES rooms(id) ON DELETE RESTRICT,
    purpose TEXT NOT NULL CHECK (purpose IN ('LIGHTING','HVAC','LANDSCAPE','GENERAL','SECURITY','OTHER')),
    enabled BOOLEAN NOT NULL DEFAULT true,
    mqtt_enabled BOOLEAN NOT NULL DEFAULT false,
    matter_enabled BOOLEAN NOT NULL DEFAULT false,
    emergency BOOLEAN NOT NULL DEFAULT false,
    hvac_control TEXT CHECK (hvac_control IN ('G','Y1','Y2','W1','W2','O/B','AUX','E','OTHER_HVAC')),
    hvac_description TEXT CHECK (length(hvac_description)<=120),
    security_endpoint_label TEXT CHECK (length(security_endpoint_label)<=120),
    other_function TEXT CHECK (length(other_function)<=120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(module_id, channel_id),
    CHECK (channel_kind='relay' OR purpose='LIGHTING'),
    CHECK (NOT emergency OR purpose='LIGHTING'),
    CHECK ((purpose='HVAC') = (hvac_control IS NOT NULL)),
    CHECK (hvac_description IS NULL OR (purpose='HVAC' AND hvac_control='OTHER_HVAC')),
    CHECK (security_endpoint_label IS NULL OR purpose='SECURITY'),
    CHECK (other_function IS NULL OR purpose='OTHER')
);
CREATE FUNCTION hcm_channel_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE role TEXT;
BEGIN
    SELECT module_type INTO role FROM modules WHERE id=NEW.module_id;
    IF TG_OP='UPDATE' AND (NEW.module_id,NEW.channel_id,NEW.channel_kind) IS DISTINCT FROM
        (OLD.module_id,OLD.channel_id,OLD.channel_kind) THEN
        RAISE EXCEPTION 'channel identity is immutable';
    END IF;
    IF NOT (TG_OP='UPDATE' AND NOT NEW.enabled) AND NOT ((role='RCM' AND NEW.channel_kind='relay' AND NEW.channel_id ~ '^[ABCD][1-8]$') OR
        (role='LCM' AND ((NEW.channel_kind='relay' AND NEW.channel_id ~ '^A[1-8]$') OR
        (NEW.channel_kind='lv_dimmer' AND NEW.channel_id ~ '^10-([1-9]|10)$') OR
        (NEW.channel_kind='hv_dimmer' AND NEW.channel_id ~ '^HV-[1-4]$')))) THEN
        RAISE EXCEPTION 'invalid physical channel identity';
    END IF;
    NEW.updated_at=now();
    RETURN NEW;
END $$;
CREATE TRIGGER channel_identity_guard BEFORE INSERT OR UPDATE ON channel_metadata
FOR EACH ROW EXECUTE FUNCTION hcm_channel_identity_guard();

CREATE FUNCTION hcm_seed_channels() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN
        UPDATE channel_metadata SET enabled=false WHERE module_id=NEW.id AND NOT (
            (NEW.module_type='RCM' AND channel_kind='relay' AND channel_id ~ '^[ABCD][1-8]$') OR
            (NEW.module_type='LCM' AND (channel_kind<>'relay' OR channel_id ~ '^A[1-8]$')));
    END IF;
    IF NEW.module_type='RCM' THEN
        INSERT INTO channel_metadata(module_id,channel_id,channel_kind,purpose)
        SELECT NEW.id,bank||n,'relay','GENERAL' FROM unnest(ARRAY['A','B','C','D']) bank CROSS JOIN generate_series(1,8) n
        ON CONFLICT DO NOTHING;
    ELSIF NEW.module_type='LCM' THEN
        INSERT INTO channel_metadata(module_id,channel_id,channel_kind,purpose)
        SELECT NEW.id,'A'||n,'relay','LIGHTING' FROM generate_series(1,8) n
        UNION ALL SELECT NEW.id,'10-'||n,'lv_dimmer','LIGHTING' FROM generate_series(1,10) n
        UNION ALL SELECT NEW.id,'HV-'||n,'hv_dimmer','LIGHTING' FROM generate_series(1,4) n
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER seed_channels AFTER INSERT OR UPDATE OF module_type ON modules FOR EACH ROW EXECUTE FUNCTION hcm_seed_channels();
-- Trigger on a no-op update only during this migration to seed existing modules.
CREATE TRIGGER seed_existing_channels AFTER UPDATE ON modules FOR EACH ROW EXECUTE FUNCTION hcm_seed_channels();
UPDATE modules SET module_type=module_type WHERE module_type IN ('RCM','LCM');
DROP TRIGGER seed_existing_channels ON modules;
UPDATE channel_metadata c SET display_name=COALESCE(d.metadata->>'channel_name',d.logical_name), room_id=d.room_id,
    purpose=CASE WHEN c.channel_kind<>'relay' THEN 'LIGHTING'
                 WHEN d.device_class='light' OR COALESCE((d.metadata->>'emergency_lighting')::boolean,false) OR COALESCE((b.metadata->>'emergency_lighting')::boolean,false) THEN 'LIGHTING' ELSE c.purpose END,
    emergency=COALESCE((d.metadata->>'emergency_lighting')::boolean,false) OR COALESCE((b.metadata->>'emergency_lighting')::boolean,false)
FROM device_bindings b JOIN logical_devices d ON d.id=b.logical_device_id
WHERE b.module_id=c.module_id AND b.channel=c.channel_id AND b.enabled;

CREATE TABLE pnl_rooms (
    module_id BIGINT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    room_id BIGINT NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY(module_id,room_id)
);
CREATE UNIQUE INDEX pnl_one_primary ON pnl_rooms(module_id) WHERE is_primary;
-- Tombstones are intentionally retained; endpoint IDs are never reused.
CREATE TABLE matter_endpoints (
    channel_id BIGINT UNIQUE REFERENCES channel_metadata(id) ON DELETE SET NULL,
    endpoint INTEGER GENERATED ALWAYS AS IDENTITY (START WITH 2 MAXVALUE 65534) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE FUNCTION hcm_registry_notify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('hcm_registry_changed',TG_TABLE_NAME);
    RETURN NULL;
END $$;
CREATE TRIGGER channel_registry_changed AFTER INSERT OR UPDATE OR DELETE ON channel_metadata
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
CREATE TRIGGER room_registry_changed AFTER INSERT OR UPDATE OR DELETE ON rooms
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
CREATE TRIGGER binding_registry_changed AFTER INSERT OR UPDATE OR DELETE ON device_bindings
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
CREATE TRIGGER module_registry_changed AFTER INSERT OR UPDATE OR DELETE ON modules
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
CREATE TRIGGER pnl_registry_changed AFTER INSERT OR UPDATE OR DELETE ON pnl_rooms
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
-- Delivery bookkeeping, never an independent source of device configuration.
CREATE TABLE bridge_publications (
    bridge TEXT NOT NULL,
    topic TEXT NOT NULL,
    PRIMARY KEY(bridge,topic)
);
CREATE TABLE bridge_settings (
    bridge TEXT PRIMARY KEY CHECK (bridge IN ('mqtt','matter')),
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER bridge_settings_changed AFTER INSERT OR UPDATE OR DELETE ON bridge_settings
FOR EACH STATEMENT EXECUTE FUNCTION hcm_registry_notify();
