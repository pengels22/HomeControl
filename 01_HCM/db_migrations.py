"""Controlled, repeat-safe PostgreSQL migration runner.

The base schema is provisioned separately.  This runner applies only numbered
additive migrations and records each successful file transactionally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted(
    path for path in (ROOT / '08_database').glob('[0-9][0-9][0-9]_*.sql')
    if not path.name.endswith('_preflight.sql')
)


async def status() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS homecontrol_schema_migrations(
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        ''')
        rows = await conn.fetch('SELECT version, filename, applied_at FROM homecontrol_schema_migrations ORDER BY version')
    return [dict(row) for row in rows]


async def migrate() -> list[int]:
    applied: list[int] = []
    async with db.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS homecontrol_schema_migrations(
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        ''')
        existing = {int(row['version']) for row in await conn.fetch('SELECT version FROM homecontrol_schema_migrations')}
        for path in MIGRATIONS:
            version = int(path.name[:3])
            if version in existing:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute(
                    'INSERT INTO homecontrol_schema_migrations(version, filename) VALUES($1,$2)',
                    version, path.name,
                )
            applied.append(version)
    return applied
