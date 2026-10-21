-- Read-only preflight for 005_module_role_switching.sql.
-- Returns rows only when existing data should be reviewed before enabling
-- HCM-controlled operational role switching.

SELECT
    'lab1_missing_or_duplicate' AS check_name,
    count(*) AS row_count,
    array_agg(id ORDER BY id) AS module_ids
FROM modules
WHERE device_id='2ccf675d3414'
HAVING count(*) <> 1

UNION ALL

SELECT
    'lab1_active_bindings' AS check_name,
    count(*) AS row_count,
    array_agg(b.id ORDER BY b.id) AS module_ids
FROM device_bindings b
JOIN modules m ON m.id=b.module_id
WHERE m.device_id='2ccf675d3414'
  AND b.enabled=true
HAVING count(*) > 0;
