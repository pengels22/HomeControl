"""Single HCM state publication helper for authenticated PNL consumers."""
from __future__ import annotations

import json
from typing import Any


MAX_EVENT_PAYLOAD = 32 * 1024
MAX_REPLAY_EVENTS = 100


async def publish_state_event(conn, device_id: str, event_type: str, payload: dict[str, Any]) -> int:
    """Append one bounded ordered event; callers use the existing DB transaction."""
    encoded = json.dumps(payload, separators=(',', ':'))
    if len(encoded.encode()) > MAX_EVENT_PAYLOAD:
        raise ValueError('PNL state event payload exceeds bounded size')
    await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', device_id)
    sequence = await conn.fetchval('SELECT COALESCE(MAX(sequence),0)+1 FROM pnl_state_events WHERE device_id=$1', device_id)
    await conn.execute('''INSERT INTO pnl_state_events(device_id,sequence,event_type,payload)
                          VALUES($1,$2,$3,$4::jsonb)''', device_id, sequence, event_type, encoded)
    return int(sequence)


async def publish_to_area(conn, area_id: int, event_type: str, payload: dict[str, Any]) -> int:
    """Publish an authorization-filtered event to every enabled panel in an area."""
    rows = await conn.fetch('SELECT device_id FROM pnl_devices WHERE area_id=$1 AND enabled=true AND revoked_at IS NULL', area_id)
    for row in rows:
        await publish_state_event(conn, row['device_id'], event_type, payload)
    return len(rows)
