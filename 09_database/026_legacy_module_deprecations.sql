-- Reversible retirement metadata for legacy SIM/RMC roles.
-- Historical modules, mappings, audit rows, and firmware records remain intact.
CREATE TABLE IF NOT EXISTS module_type_deprecations (
    module_type TEXT PRIMARY KEY CHECK (module_type IN ('SIM','RMC')),
    status TEXT NOT NULL DEFAULT 'DEPRECATED'
        CHECK (status IN ('DEPRECATED','RETIRED')),
    reason TEXT NOT NULL,
    deprecated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ
);

INSERT INTO module_type_deprecations(module_type, status, reason)
VALUES
    ('SIM', 'DEPRECATED', 'Legacy sensor/CAN gateway retained for compatibility while PNL replaces its consumer surface'),
    ('RMC', 'DEPRECATED', 'Legacy CAN room sensor node retained for historical data and rollback compatibility')
ON CONFLICT (module_type) DO NOTHING;
