-- Read-only preflight for 004_phase4_registry_hardening.sql.
-- Run before applying migration 004 to identify existing rows that would
-- violate the active physical binding uniqueness indexes. This script does
-- not modify data.

SELECT
    'active_channel_conflict' AS conflict_type,
    module_id,
    channel,
    NULL::text AS binding_type,
    count(*) AS binding_count,
    array_agg(id ORDER BY id) AS binding_ids,
    array_agg(logical_device_id ORDER BY id) AS logical_device_ids
FROM device_bindings
WHERE enabled = true
  AND channel IS NOT NULL
GROUP BY module_id, channel
HAVING count(*) > 1

UNION ALL

SELECT
    'active_null_channel_conflict' AS conflict_type,
    module_id,
    NULL::text AS channel,
    binding_type,
    count(*) AS binding_count,
    array_agg(id ORDER BY id) AS binding_ids,
    array_agg(logical_device_id ORDER BY id) AS logical_device_ids
FROM device_bindings
WHERE enabled = true
  AND channel IS NULL
GROUP BY module_id, binding_type
HAVING count(*) > 1

ORDER BY conflict_type, module_id, channel, binding_type;
