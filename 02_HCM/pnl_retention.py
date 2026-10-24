"""Explicit, bounded PNL data-retention maintenance.

No retention job runs implicitly at application startup. Operators or a reviewed
maintenance scheduler call ``purge_pnl_data`` with the documented policy.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PNLRetentionPolicy:
    telemetry_days: int = 30
    occupancy_days: int = 30
    command_ledger_days: int = 7
    state_events_days: int = 7
    session_days: int = 1

    def __post_init__(self):
        if any(value < 1 for value in (self.telemetry_days, self.occupancy_days, self.command_ledger_days, self.state_events_days, self.session_days)):
            raise ValueError('PNL retention periods must be positive')


async def purge_pnl_data(conn, policy: PNLRetentionPolicy = PNLRetentionPolicy(), *, execute: bool = False) -> dict[str, object]:
    """Return planned row counts, or execute explicit bounded deletes.

    Current local state, credentials, audit rows, and published revisions are
    never targeted. ``execute=False`` is the safe default for dry-run review.
    """
    statements = {
        'telemetry': ('pnl_telemetry_events', policy.telemetry_days),
        'occupancy': ('pnl_occupancy_events', policy.occupancy_days),
        'command_ledger': ('pnl_command_ledger', policy.command_ledger_days),
        'state_events': ('pnl_state_events', policy.state_events_days),
    }
    result: dict[str, object] = {'execute': execute, 'policy': policy.__dict__.copy(), 'deleted': {}}
    for key, (table, days) in statements.items():
        if execute:
            result['deleted'][key] = await conn.fetchval(f"DELETE FROM {table} WHERE created_at < now() - ($1::text || ' days')::interval RETURNING 1", str(days))
        else:
            result['deleted'][key] = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE created_at < now() - ($1::text || ' days')::interval", str(days))
    return result
