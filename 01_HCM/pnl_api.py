from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .auth import require_user
from .pnl_backplane import PNLTelemetryError, local_aliases, validate_telemetry, verify_token

router = APIRouter(prefix='/api/v1/pnl')


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: str = Field(pattern=r'^[0-9a-f]{12}$')
    sequence: int = Field(ge=0)
    timestamp: str
    local: dict[str, object]


@router.post('/telemetry')
async def ingest_telemetry(body: TelemetryIn, authorization: str | None = Header(default=None),
                            x_pnl_device: str | None = Header(default=None)):
    token = authorization.removeprefix('Bearer ').strip() if authorization else ''
    if not x_pnl_device or x_pnl_device != body.device_id or not token:
        raise HTTPException(401, 'PNL identity and bearer token are required')
    async with db.acquire() as conn:
        device = await conn.fetchrow('SELECT * FROM pnl_devices WHERE device_id=$1 AND enabled=true', body.device_id)
        if not device or not verify_token(token, device['token_hash']):
            raise HTTPException(401, 'PNL authentication failed')
        try:
            payload = validate_telemetry(body.model_dump(), device_id=body.device_id,
                                         last_sequence=int(device['last_sequence']))
        except PNLTelemetryError as exc:
            raise HTTPException(422, str(exc)) from None
        async with conn.transaction():
            await conn.execute('''INSERT INTO pnl_telemetry_events(device_id,sequence,payload)
                                  VALUES($1,$2,$3::jsonb)''', body.device_id, body.sequence, json.dumps(payload))
            await conn.execute('''UPDATE pnl_devices SET last_sequence=$2,last_telemetry_at=now(),
                                  local_state=$3::jsonb,updated_at=now() WHERE device_id=$1''',
                               body.device_id, body.sequence, json.dumps(payload['local']))
    return {'ok': True, 'device_id': body.device_id, 'sequence': body.sequence,
            'stale_after_seconds': 15, 'local_aliases': local_aliases(body.device_id, payload['local'])}


@router.get('/devices')
async def pnl_devices(user=Depends(require_user)):
    async with db.acquire() as conn:
        rows = await conn.fetch('''SELECT device_id,area_id,enabled,last_sequence,last_telemetry_at,
                                  local_state,dashboard_revision FROM pnl_devices ORDER BY device_id''')
    return {'devices': [dict(row) for row in rows]}


@router.get('/devices/{device_id}/aliases')
async def pnl_aliases(device_id: str, user=Depends(require_user)):
    async with db.acquire() as conn:
        row = await conn.fetchrow('SELECT local_state,last_telemetry_at FROM pnl_devices WHERE device_id=$1', device_id)
    if not row:
        raise HTTPException(404, 'PNL device not found')
    last = row['last_telemetry_at']
    stale = last is None or (datetime.now(timezone.utc) - last).total_seconds() > 15
    return {'device_id': device_id, 'stale': stale,
            'aliases': local_aliases(device_id, row['local_state'] or {})}
