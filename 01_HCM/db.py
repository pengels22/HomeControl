from __future__ import annotations
import asyncpg
from contextlib import asynccontextmanager
from .settings import settings

_pool: asyncpg.Pool | None = None

async def connect():
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError('HCM_DATABASE_URL is required; no database credential fallback is permitted')
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool

async def close():
    global _pool
    if _pool is not None:
        await _pool.close(); _pool = None

@asynccontextmanager
async def acquire():
    pool = await connect()
    async with pool.acquire() as conn:
        yield conn
