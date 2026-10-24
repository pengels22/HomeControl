from importlib import import_module
import os
import uuid
import asyncpg
import pytest


def test_migration_runner_is_numbered_and_ordered():
    migrations = import_module('01_HCM.db_migrations')
    versions = [int(path.name[:3]) for path in migrations.MIGRATIONS]

    assert versions == sorted(versions)
    assert versions == list(range(1, 27))


async def test_hcm_areas_migrate_from_previous_schema_without_losing_rooms():
    url = os.getenv('HCM_TEST_DATABASE_URL')
    if not url:
        pytest.skip('HCM_TEST_DATABASE_URL required for PostgreSQL integration tests')
    migrations = import_module('01_HCM.db_migrations')
    conn = await asyncpg.connect(url)
    schema = 'areas_migration_' + uuid.uuid4().hex
    await conn.execute(f'CREATE SCHEMA {schema}')
    await conn.execute(f'SET search_path TO {schema},public')
    try:
        await conn.execute((migrations.ROOT / '09_database/schema.sql').read_text())
        await conn.execute("INSERT INTO rooms(id,name) VALUES(901,'Existing Room')")
        for path in migrations.MIGRATIONS:
            if int(path.name[:3]) >= 25:
                break
            await conn.execute(path.read_text())
        assert await conn.fetchval("SELECT to_regclass('hcm_areas')") is None
        await conn.execute((migrations.ROOT / '09_database/025_hcm_areas.sql').read_text())
        assert await conn.fetchval('SELECT area_id FROM rooms WHERE id=901') is None
        assert await conn.fetchval('SELECT name FROM rooms WHERE id=901') == 'Existing Room'
        area_id = await conn.fetchval("INSERT INTO hcm_areas(name) VALUES('Main Floor') RETURNING id")
        await conn.execute('UPDATE rooms SET area_id=$1 WHERE id=901', area_id)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute('DELETE FROM hcm_areas WHERE id=$1', area_id)
        assert await conn.fetchval('SELECT area_id FROM rooms WHERE id=901') == area_id
        assert await conn.fetchval("SELECT to_regclass('acm_areas')") is None
    finally:
        await conn.execute('SET search_path TO public')
        await conn.execute(f'DROP SCHEMA {schema} CASCADE')
        await conn.close()
