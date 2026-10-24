"""Read-only legacy SIM/RMC retirement status.

This module deliberately does not unregister modules or delete historical data.
It gives administration and later migration passes one authoritative status
shape while compatibility paths remain available.
"""

from __future__ import annotations

from typing import Any

from . import db


async def status() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT module_type, status, reason, deprecated_at, retired_at
               FROM module_type_deprecations ORDER BY module_type"""
        )
    return [dict(row) for row in rows]
