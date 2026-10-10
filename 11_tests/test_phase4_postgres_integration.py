from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest

from importlib import import_module

management = import_module('01_HCM.management')


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get('HCM_TEST_DATABASE_URL')

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason='set HCM_TEST_DATABASE_URL to run PostgreSQL integration tests',
)


@asynccontextmanager
async def postgres_conn():
    conn = await asyncpg.connect(DATABASE_URL)
    schema = f"phase4_test_{uuid.uuid4().hex}"
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    await conn.execute(f'SET search_path TO "{schema}"')
    try:
        for rel in (
            '08_database/schema.sql',
            '08_database/001_device_identity_migration.sql',
            '08_database/002_safety_arbitration.sql',
            '08_database/003_module_registry_foundation.sql',
            '08_database/004_phase4_registry_hardening.sql',
        ):
            await conn.execute((ROOT / rel).read_text())
        yield conn
    finally:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()


class SingleConnectionAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def seed_lcm(conn):
    module_id = await conn.fetchval(
        """
        INSERT INTO modules(device_id, module_type, hostname, ip_address, online)
        VALUES('48b02d87db16','LCM','LCM01','192.168.20.30',true)
        RETURNING id
        """
    )
    for capability in ('analog-out-8', 'lighting'):
        await conn.execute(
            "INSERT INTO module_capabilities(module_id, capability) VALUES($1,$2)",
            module_id,
            capability,
        )
    await conn.execute(
        "INSERT INTO logical_devices(logical_name, device_class) VALUES('Kitchen Light','light')"
    )
    await conn.execute(
        "INSERT INTO logical_devices(logical_name, device_class) VALUES('Hall Light','light')"
    )


@pytest.mark.asyncio
async def test_phase4_migrations_are_repeat_safe():
    async with postgres_conn() as conn:
        await conn.execute((ROOT / '08_database/003_module_registry_foundation.sql').read_text())
        await conn.execute((ROOT / '08_database/004_phase4_registry_hardening.sql').read_text())
        tables = await conn.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname=current_schema()
              AND tablename IN ('module_capabilities','device_management_events')
            ORDER BY tablename
            """
        )
        assert [row['tablename'] for row in tables] == ['device_management_events', 'module_capabilities']


@pytest.mark.asyncio
async def test_management_mutation_rolls_back_when_audit_fails(monkeypatch):
    async with postgres_conn() as conn:
        monkeypatch.setattr(management.db, 'acquire', lambda: SingleConnectionAcquire(conn))

        async def failing_audit(*args, **kwargs):
            raise RuntimeError('audit down')

        monkeypatch.setattr(management, 'audit_event', failing_audit)

        with pytest.raises(RuntimeError, match='audit down'):
            await management.create_logical_device(
                logical_name='Rollback Light',
                device_class='light',
                actor='patrick',
            )

        count = await conn.fetchval(
            "SELECT count(*) FROM logical_devices WHERE logical_name='Rollback Light'"
        )
        assert count == 0


@pytest.mark.asyncio
async def test_duplicate_active_binding_rejected_by_management_and_index(monkeypatch):
    async with postgres_conn() as conn:
        await seed_lcm(conn)
        monkeypatch.setattr(management.db, 'acquire', lambda: SingleConnectionAcquire(conn))

        await management.create_binding(
            logical_name='Kitchen Light',
            module_identifier='LCM01',
            channel='10-1',
            actor='patrick',
        )
        with pytest.raises(management.ValidationError):
            await management.create_binding(
                logical_name='Hall Light',
                module_identifier='LCM01',
                channel='10-1',
                actor='patrick',
            )

        hall_id = await conn.fetchval("SELECT id FROM logical_devices WHERE logical_name='Hall Light'")
        module_id = await conn.fetchval("SELECT id FROM modules WHERE hostname='LCM01'")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                """
                INSERT INTO device_bindings(logical_device_id, module_id, channel, binding_type, enabled)
                VALUES($1,$2,'10-1','primary',true)
                """,
                hall_id,
                module_id,
            )


@pytest.mark.asyncio
async def test_concurrent_duplicate_binding_update_loses_to_unique_index(monkeypatch):
    async with postgres_conn() as conn:
        await seed_lcm(conn)
        kitchen_id = await conn.fetchval("SELECT id FROM logical_devices WHERE logical_name='Kitchen Light'")
        hall_id = await conn.fetchval("SELECT id FROM logical_devices WHERE logical_name='Hall Light'")
        module_id = await conn.fetchval("SELECT id FROM modules WHERE hostname='LCM01'")
        b1 = await conn.fetchval(
            "INSERT INTO device_bindings(logical_device_id,module_id,channel,enabled) VALUES($1,$2,'10-1',false) RETURNING id",
            kitchen_id,
            module_id,
        )
        b2 = await conn.fetchval(
            "INSERT INTO device_bindings(logical_device_id,module_id,channel,enabled) VALUES($1,$2,'10-1',false) RETURNING id",
            hall_id,
            module_id,
        )

        await conn.execute("UPDATE device_bindings SET enabled=true WHERE id=$1", b1)
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("UPDATE device_bindings SET enabled=true WHERE id=$1", b2)


@pytest.mark.asyncio
async def test_room_assignment_can_be_cleared_with_audit(monkeypatch):
    async with postgres_conn() as conn:
        monkeypatch.setattr(management.db, 'acquire', lambda: SingleConnectionAcquire(conn))
        room_id = await conn.fetchval(
            "INSERT INTO rooms(name, floor) VALUES('Kitchen','1') RETURNING id"
        )
        await management.create_logical_device(
            logical_name='Kitchen Pendant',
            device_class='light',
            room_id=room_id,
            actor='patrick',
        )

        updated = await management.update_logical_device(
            'Kitchen Pendant',
            actor='patrick',
            room_id=None,
        )

        assert updated['room_id'] is None
        stored_room_id = await conn.fetchval(
            "SELECT room_id FROM logical_devices WHERE logical_name='Kitchen Pendant'"
        )
        assert stored_room_id is None
        audit_count = await conn.fetchval(
            """
            SELECT count(*)
            FROM device_management_events
            WHERE action='logical_device.update'
              AND target_type='logical_device'
            """
        )
        assert audit_count == 1


@pytest.mark.asyncio
async def test_null_channel_active_binding_conflicts_are_rejected(monkeypatch):
    async with postgres_conn() as conn:
        monkeypatch.setattr(management.db, 'acquire', lambda: SingleConnectionAcquire(conn))
        module_id = await conn.fetchval(
            """
            INSERT INTO modules(device_id, module_type, hostname, ip_address, online)
            VALUES('48b02d87db18','PNL','PNL01','192.168.20.50',true)
            RETURNING id
            """
        )
        await conn.execute(
            "INSERT INTO module_capabilities(module_id, capability) VALUES($1,'panel')",
            module_id,
        )
        await conn.execute(
            "INSERT INTO logical_devices(logical_name, device_class) VALUES('Wall Panel','panel')"
        )
        await conn.execute(
            "INSERT INTO logical_devices(logical_name, device_class) VALUES('Entry Panel','panel')"
        )

        await management.create_binding(
            logical_name='Wall Panel',
            module_identifier='PNL01',
            channel=None,
            actor='patrick',
            binding_type='primary',
        )
        with pytest.raises(management.ValidationError):
            await management.create_binding(
                logical_name='Entry Panel',
                module_identifier='PNL01',
                channel=None,
                actor='patrick',
                binding_type='primary',
            )

        entry_id = await conn.fetchval(
            "SELECT id FROM logical_devices WHERE logical_name='Entry Panel'"
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                """
                INSERT INTO device_bindings(logical_device_id, module_id, channel, binding_type, enabled)
                VALUES($1,$2,NULL,'primary',true)
                """,
                entry_id,
                module_id,
            )


@pytest.mark.asyncio
async def test_module_replacement_preserves_logical_device_identity(monkeypatch):
    async with postgres_conn() as conn:
        monkeypatch.setattr(management.db, 'acquire', lambda: SingleConnectionAcquire(conn))
        old_module_id = await conn.fetchval(
            """
            INSERT INTO modules(device_id, module_type, hostname, ip_address, online)
            VALUES('48b02d87db16','LCM','LCM01','192.168.20.30',true)
            RETURNING id
            """
        )
        new_module_id = await conn.fetchval(
            """
            INSERT INTO modules(device_id, module_type, hostname, ip_address, online)
            VALUES('48b02d87db1a','LCM','LCM02','192.168.20.31',true)
            RETURNING id
            """
        )
        for module_id in (old_module_id, new_module_id):
            await conn.execute(
                "INSERT INTO module_capabilities(module_id, capability) VALUES($1,'analog-out-8')",
                module_id,
            )
        logical_id = await conn.fetchval(
            """
            INSERT INTO logical_devices(logical_name, device_class)
            VALUES('Kitchen Light','light')
            RETURNING id
            """
        )
        await conn.execute(
            """
            INSERT INTO device_bindings(logical_device_id,module_id,channel,enabled)
            VALUES($1,$2,'10-1',true)
            """,
            logical_id,
            old_module_id,
        )

        await conn.execute("DELETE FROM modules WHERE id=$1", old_module_id)
        assert await conn.fetchval("SELECT count(*) FROM device_bindings") == 0

        rebound = await management.create_binding(
            logical_name='Kitchen Light',
            module_identifier='LCM02',
            channel='10-1',
            actor='patrick',
        )

        assert rebound['logical_device_id'] == logical_id
        stored = await conn.fetchrow(
            "SELECT id, logical_name FROM logical_devices WHERE id=$1",
            logical_id,
        )
        assert dict(stored) == {'id': logical_id, 'logical_name': 'Kitchen Light'}
