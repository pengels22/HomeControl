from importlib import import_module
from unittest.mock import AsyncMock
import pytest

contract = import_module('01_HCM.schema_contract')
migrations = import_module('01_HCM.db_migrations')

async def test_schema_check_catches_live_login_regression_without_writes():
    rows = [{'table_name': t, 'column_name': c} for t, columns in contract.REQUIRED_COLUMNS.items()
            for c in columns if t != 'auth_login_rate_limits']
    conn = AsyncMock()
    conn.fetch.return_value = rows
    with pytest.raises(RuntimeError, match='auth_login_rate_limits'):
        await contract.check_schema(conn)
    conn.execute.assert_not_called()

async def test_schema_check_accepts_current_contract():
    conn = AsyncMock()
    conn.fetch.return_value = [{'table_name': t, 'column_name': c}
                              for t, cols in contract.REQUIRED_COLUMNS.items() for c in cols]
    assert (await contract.check_schema(conn))['ok']
    conn.execute.assert_not_called()

class Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): pass

async def test_migration_status_is_read_only_when_tracking_table_missing(monkeypatch):
    conn = AsyncMock(); conn.fetchval.return_value = None
    monkeypatch.setattr(migrations.db, 'acquire', lambda: Acquire(conn))
    assert await migrations.status() == []
    conn.execute.assert_not_called()

async def test_only_explicitly_selected_migrations_run(monkeypatch):
    from unittest.mock import Mock
    conn = AsyncMock(); conn.fetch.return_value = []
    conn.transaction = Mock(return_value=Acquire(conn))
    monkeypatch.setattr(migrations.db, 'acquire', lambda: Acquire(conn))
    assert await migrations.migrate([6,7]) == [6,7]
    sql = '\n'.join(str(call.args[0]) for call in conn.execute.call_args_list)
    assert 'CREATE TABLE IF NOT EXISTS auth_login_rate_limits' in sql
    assert 'CREATE TABLE IF NOT EXISTS touchscreen_devices' in sql
    assert 'ALTER TABLE modules' not in sql

async def test_invalid_migration_selection_fails_before_db_access(monkeypatch):
    def fail(): raise AssertionError('DB accessed')
    monkeypatch.setattr(migrations.db, 'acquire', fail)
    with pytest.raises(ValueError): await migrations.migrate([999])
