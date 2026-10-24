"""Read-only legacy SIM/RMC retirement status.

This module deliberately does not unregister modules or delete historical data.
It gives administration and later migration passes one authoritative status
shape while compatibility paths remain available.
"""

from __future__ import annotations

from typing import Any

from . import db

LEGACY_ROLES = frozenset({'SIM', 'RMC'})
NEW_INSTALL_ROLES = frozenset({'RCM', 'LCM', 'PNL'})


def role_available_for_new_install(role: str) -> bool:
    """Fresh-install policy; existing legacy role records remain readable."""
    return str(role or '').upper() in NEW_INSTALL_ROLES


async def status() -> list[dict[str, Any]]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT module_type, status, reason, deprecated_at, retired_at
               FROM module_type_deprecations ORDER BY module_type"""
        )
    return [dict(row) for row in rows]
