"""Read-only schema prerequisites for the current authentication/application API."""
REQUIRED_COLUMNS = {
    'users': {'username', 'role', 'password_hash', 'enabled', 'touchscreen_pin_hash',
              'touchscreen_pin_lookup', 'touchscreen_pin_enabled', 'touchscreen_permission',
              'touchscreen_pin_changed_at', 'touchscreen_session_policy'},
    'user_sessions': {'username', 'token_hash', 'role', 'expires_at', 'revoked_at'},
    'auth_login_rate_limits': {'scope', 'failed_attempts', 'next_allowed_at', 'last_failed_at', 'updated_at'},
    'touchscreen_devices': {'id', 'device_id', 'token_hash', 'enabled', 'permitted_module_ids', 'revoked_at'},
    'touchscreen_sessions': {'user_id', 'device_id', 'token_hash', 'permission', 'last_activity_at',
                            'idle_expires_at', 'absolute_expires_at', 'revoked_at', 'revoke_reason'},
    'touchscreen_rate_limits': {'scope', 'failed_attempts', 'next_allowed_at', 'last_failed_at', 'updated_at'},
}


async def check_schema(conn):
    rows = await conn.fetch("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'")
    present = {}
    for row in rows:
        present.setdefault(row['table_name'], set()).add(row['column_name'])
    missing = [table + '.' + column for table, columns in REQUIRED_COLUMNS.items()
               for column in sorted(columns - present.get(table, set()))]
    if missing:
        raise RuntimeError('HCM schema prerequisites missing: ' + ', '.join(missing) +
                           '; review backup and migrations before replacing HCM')
    return {'ok': True, 'schema_contract': 'authentication-v7'}
