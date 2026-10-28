"""PostgreSQL-backed production PNL administration and panel APIs.

Panel credentials are independent bearer tokens. Administrative routes use the
existing HCM user session and ADMIN role; panel routes never accept browser
sessions. The bounded event endpoint is the initial firmware-compatible state
transport and always resynchronizes from a capped snapshot.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from homecontrol_identity import InvalidDeviceId, normalize_device_id

from . import db, entities
from .auth import require_user
from .devices import command_logical
from .pnl_backplane import STALE_AFTER_SECONDS, local_aliases, token_hash, verify_token
from .pnl_events import MAX_REPLAY_EVENTS

dashboard = import_module('05_PNL.dashboard')
reference_dashboard = import_module('05_PNL.reference_dashboard')

router = APIRouter(prefix='/api/v1/pnl-production')
FALLBACK_LAYOUT = reference_dashboard.REFERENCE_DASHBOARD


def _admin(user):
    if user.get('role') != 'ADMIN':
        raise HTTPException(403, 'ADMIN role required')


def _panel_headers(authorization: str | None, device: str | None) -> tuple[str, str]:
    token = authorization.removeprefix('Bearer ').strip() if authorization else ''
    if not token or not device:
        raise HTTPException(401, 'PNL identity and bearer token are required')
    try:
        return normalize_device_id(device), token
    except InvalidDeviceId:
        raise HTTPException(401, 'invalid PNL identity') from None


async def _panel(conn, device: str, token: str, *, lock: bool = False):
    suffix = ' FOR UPDATE' if lock else ''
    row = await conn.fetchrow(f'SELECT * FROM pnl_devices WHERE device_id=$1{suffix}', device)
    if not row or not row['enabled'] or row['revoked_at'] is not None or not verify_token(token, row['token_hash']):
        raise HTTPException(401, 'PNL authentication failed')
    return row


async def _area_entities(area_id: int | None):
    catalog = await entities.list_channel_entities()
    if area_id is None:
        return catalog
    return [item for item in catalog if item.get('area_id') in (None, area_id)]


async def _dashboard_for(conn, device_id: str, area_id: int | None):
    row = await conn.fetchrow('''SELECT d.id,d.name,d.scope,r.revision,r.layout,r.layout_sha256,1 AS priority
        FROM dashboard_assignments a JOIN dashboard_documents d ON d.id=a.dashboard_id
        JOIN dashboard_revisions r ON r.dashboard_id=d.id AND r.revision=d.published_revision
        WHERE a.pnl_device_id=$1 AND a.is_primary AND d.published_revision IS NOT NULL
        UNION ALL
        SELECT d.id,d.name,d.scope,r.revision,r.layout,r.layout_sha256,2 AS priority
        FROM dashboard_assignments a JOIN dashboard_documents d ON d.id=a.dashboard_id
        JOIN dashboard_revisions r ON r.dashboard_id=d.id AND r.revision=d.published_revision
        WHERE a.area_id=$2 AND a.is_primary AND d.published_revision IS NOT NULL
        ORDER BY priority,id LIMIT 1''', device_id, area_id)
    if not row:
        row = await conn.fetchrow('''SELECT d.id,d.name,d.scope,r.revision,r.layout,r.layout_sha256
            FROM dashboard_documents d JOIN dashboard_revisions r ON r.dashboard_id=d.id AND r.revision=d.published_revision
            WHERE d.scope='shared' AND d.published_revision IS NOT NULL ORDER BY d.id LIMIT 1''')
    if not row:
        compiled = dashboard.compile_dashboard(FALLBACK_LAYOUT)
        return {'id': None, 'name': 'local-fallback', 'revision': 0, 'layout': compiled['layout'], 'sha256': compiled['sha256']}
    try:
        compiled = dashboard.compile_dashboard(row['layout'])
    except dashboard.DashboardError:
        return {'id': None, 'name': 'local-fallback', 'revision': 0, 'layout': FALLBACK_LAYOUT, 'sha256': dashboard.compile_dashboard(FALLBACK_LAYOUT)['sha256']}
    return {'id': row['id'], 'name': row['name'], 'scope': row['scope'], 'revision': row['revision'], 'layout': compiled['layout'], 'sha256': compiled['sha256']}


class RegisterPNL(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: str
    friendly_id: str = Field(min_length=1, max_length=80)
    hostname: str = Field(min_length=1, max_length=120)
    area_id: int | None = Field(default=None, ge=1)
    software_version: str = Field(default='unknown', max_length=80)


class UpdatePNL(BaseModel):
    model_config = ConfigDict(extra='forbid')
    friendly_id: str | None = Field(default=None, min_length=1, max_length=80)
    hostname: str | None = Field(default=None, min_length=1, max_length=120)
    area_id: int | None = Field(default=None, ge=1)
    software_version: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


class Assignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dashboard_id: int = Field(ge=1)
    pnl_device_id: str | None = None
    area_id: int | None = Field(default=None, ge=1)


class CommandIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=120)
    card_type: str
    entity: str = Field(min_length=1, max_length=200)
    value: Any
    ttl_seconds: int = Field(default=30, ge=1, le=120)


class OccupancyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sequence: int = Field(ge=0)
    event_key: str = Field(min_length=1, max_length=120)
    occupied: bool | None
    occurred_at: str


class SonicAck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    epoch: int = Field(ge=1)
    muted: bool


@router.post('/admin/devices')
async def register_pnl(body: RegisterPNL, user=Depends(require_user)):
    _admin(user)
    try:
        device_id = normalize_device_id(body.device_id)
    except InvalidDeviceId:
        raise HTTPException(422, 'device_id must be a valid physical-interface MAC') from None
    token = secrets.token_urlsafe(32)
    async with db.acquire() as conn:
        async with conn.transaction():
            if body.area_id and not await conn.fetchval('SELECT 1 FROM hcm_areas WHERE id=$1 AND enabled', body.area_id):
                raise HTTPException(422, 'area is not enabled')
            try:
                row = await conn.fetchrow('''INSERT INTO pnl_devices(device_id,friendly_id,hostname,area_id,software_version,token_hash)
                    VALUES($1,$2,$3,$4,$5,$6) RETURNING device_id,token_generation''', device_id, body.friendly_id, body.hostname, body.area_id, body.software_version, token_hash(token))
                await conn.execute('''INSERT INTO pnl_credentials_audit(device_id,token_generation,token_hash,reason)
                    VALUES($1,$2,$3,'initial registration')''', device_id, row['token_generation'], token_hash(token))
            except Exception as exc:
                if 'duplicate' in str(exc).lower() or 'unique' in str(exc).lower():
                    raise HTTPException(409, 'PNL identity or friendly_id already registered') from None
                raise
    return {'device_id': device_id, 'friendly_id': body.friendly_id, 'token': token, 'token_generation': 1}


@router.get('/admin/devices')
async def list_registered_pnls(user=Depends(require_user)):
    _admin(user)
    async with db.acquire() as conn:
        rows = await conn.fetch('''SELECT device_id,friendly_id,hostname,area_id,enabled,software_version,
            token_generation,revoked_at,last_sequence,last_telemetry_at,last_heartbeat_at,last_sonic_epoch,last_sonic_muted,dashboard_revision
            FROM pnl_devices ORDER BY friendly_id,device_id''')
    return {'devices': [dict(row) for row in rows], 'stale_after_seconds': STALE_AFTER_SECONDS}


@router.get('/admin/entity-catalog')
async def admin_entity_catalog(area_id: int | None = None, user=Depends(require_user)):
    _admin(user)
    return {'area_id': area_id, 'entities': await _area_entities(area_id)}


@router.patch('/admin/devices/{device_id}')
async def update_registered_pnl(device_id: str, body: UpdatePNL, user=Depends(require_user)):
    _admin(user)
    try:
        device_id = normalize_device_id(device_id)
    except InvalidDeviceId:
        raise HTTPException(422, 'invalid PNL identity') from None
    changes = body.model_dump(exclude_unset=True)
    async with db.acquire() as conn:
        async with conn.transaction():
            if body.area_id and not await conn.fetchval('SELECT 1 FROM hcm_areas WHERE id=$1 AND enabled', body.area_id):
                raise HTTPException(422, 'area is not enabled')
            row = await conn.fetchrow('SELECT device_id FROM pnl_devices WHERE device_id=$1 FOR UPDATE', device_id)
            if not row:
                raise HTTPException(404, 'PNL not found')
            if changes:
                fields = ', '.join(f'{key}=${index + 2}' for index, key in enumerate(changes))
                await conn.execute(f'UPDATE pnl_devices SET {fields},updated_at=now() WHERE device_id=$1', device_id, *changes.values())
    return {'ok': True, 'device_id': device_id}


@router.post('/admin/devices/{device_id}/rotate-credentials')
async def rotate_pnl_credentials(device_id: str, user=Depends(require_user)):
    _admin(user)
    device_id = normalize_device_id(device_id)
    token = secrets.token_urlsafe(32)
    async with db.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT token_generation FROM pnl_devices WHERE device_id=$1 FOR UPDATE', device_id)
            if not row:
                raise HTTPException(404, 'PNL not found')
            generation = int(row['token_generation']) + 1
            await conn.execute('UPDATE pnl_devices SET token_hash=$2,token_generation=$3,revoked_at=NULL,enabled=true,updated_at=now() WHERE device_id=$1', device_id, token_hash(token), generation)
            await conn.execute('UPDATE pnl_credentials_audit SET revoked_at=now() WHERE device_id=$1 AND revoked_at IS NULL', device_id)
            await conn.execute('INSERT INTO pnl_credentials_audit(device_id,token_generation,token_hash,reason) VALUES($1,$2,$3,\'credential rotation\')', device_id, generation, token_hash(token))
    return {'device_id': device_id, 'token': token, 'token_generation': generation}


@router.post('/admin/devices/{device_id}/revoke')
async def revoke_pnl(device_id: str, user=Depends(require_user)):
    _admin(user)
    device_id = normalize_device_id(device_id)
    async with db.acquire() as conn:
        updated = await conn.execute('UPDATE pnl_devices SET enabled=false,revoked_at=now(),updated_at=now() WHERE device_id=$1', device_id)
    if updated == 'UPDATE 0':
        raise HTTPException(404, 'PNL not found')
    return {'ok': True, 'device_id': device_id, 'revoked': True}


@router.post('/admin/dashboard-assignments')
async def assign_dashboard(body: Assignment, user=Depends(require_user)):
    _admin(user)
    if bool(body.pnl_device_id) == bool(body.area_id):
        raise HTTPException(422, 'exactly one panel or area target is required')
    async with db.acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval('SELECT 1 FROM dashboard_documents WHERE id=$1', body.dashboard_id):
                raise HTTPException(404, 'dashboard not found')
            if not await conn.fetchval('SELECT published_revision FROM dashboard_documents WHERE id=$1', body.dashboard_id):
                raise HTTPException(409, 'only published dashboards may be assigned')
            target = body.pnl_device_id or body.area_id
            await conn.execute('''UPDATE dashboard_assignments SET is_primary=false
                WHERE is_primary AND ((pnl_device_id=$1 AND $1 IS NOT NULL) OR (area_id=$2 AND $2 IS NOT NULL))''', body.pnl_device_id, body.area_id)
            await conn.execute('''INSERT INTO dashboard_assignments(dashboard_id,pnl_device_id,area_id,is_primary)
                VALUES($1,$2,$3,true) ON CONFLICT (dashboard_id,pnl_device_id,area_id)
                DO UPDATE SET is_primary=true''', body.dashboard_id, body.pnl_device_id, body.area_id)
    return {'ok': True, 'dashboard_id': body.dashboard_id, 'target': target}


@router.get('/panel/config')
async def panel_config(response: Response, authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None), if_none_match: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        panel = await _panel(conn, device_id, token)
        selected = await _dashboard_for(conn, device_id, panel['area_id'])
        catalog = await _area_entities(panel['area_id'])
    if if_none_match and if_none_match.strip('"') == selected['sha256']:
        response.status_code = 304
        return None
    return {'device_id': device_id, 'friendly_id': panel['friendly_id'], 'hostname': panel['hostname'], 'area_id': panel['area_id'], 'dashboard': selected, 'catalog': catalog, 'local_aliases': local_aliases(device_id, panel['local_state'] or {}), 'schema_version': 1, 'compiler_version': 1}


@router.get('/panel/state')
async def panel_state(authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        panel = await _panel(conn, device_id, token)
        catalog = await _area_entities(panel['area_id'])
    return {'sequence': 0, 'device_id': device_id, 'area_id': panel['area_id'], 'entities': catalog, 'local': panel['local_state'] or {}}


@router.get('/panel/events')
async def panel_events(since: int = 0, authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        await _panel(conn, device_id, token)
        rows = await conn.fetch('''SELECT sequence,event_type,payload,created_at FROM pnl_state_events
            WHERE device_id=$1 AND sequence>$2 ORDER BY sequence LIMIT $3''', device_id, since, MAX_REPLAY_EVENTS)
    return {'events': [dict(row) for row in rows], 'next_sequence': rows[-1]['sequence'] if rows else since, 'bounded': True}


@router.post('/panel/commands')
async def panel_command(body: CommandIn, authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    now = datetime.now(timezone.utc)
    async with db.acquire() as conn:
        panel = await _panel(conn, device_id, token, lock=True)
        catalog = await _area_entities(panel['area_id'])
        descriptor = next((item for item in catalog if item.get('logical_name') == body.entity or item.get('entity_id') == body.entity), None)
        if not descriptor or not descriptor.get('writable'):
            raise HTTPException(403, 'entity is not authorized or writable for this panel')
        async with conn.transaction():
            existing = await conn.fetchrow('SELECT response,status FROM pnl_command_ledger WHERE device_id=$1 AND request_id=$2', device_id, body.request_id)
            if existing:
                return {**(existing['response'] or {}), 'status': 'duplicate'}
            command = {'op': 'set_dimmer', 'percent': body.value} if body.card_type == 'slider' else {'op': 'set_relay', 'value': body.value}
            if body.card_type == 'thermostat':
                command = {'op': 'thermostat', 'value': body.value}
            logical = descriptor.get('logical_name') or body.entity
            try:
                result = await command_logical(logical, command, source='pnl')
                status = 'accepted'
                result = {'request_id': body.request_id, 'status': status, 'physical_success': False, 'result': result}
            except Exception as exc:
                status = 'failed'
                result = {'request_id': body.request_id, 'status': status, 'reason': str(exc)}
            await conn.execute('''INSERT INTO pnl_command_ledger(device_id,request_id,logical_entity,status,response,expires_at)
                VALUES($1,$2,$3,$4,$5::jsonb,$6)''', device_id, body.request_id, logical, status, json.dumps(result), now + timedelta(seconds=body.ttl_seconds))
    return result


@router.post('/panel/occupancy')
async def panel_occupancy(body: OccupancyIn, authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    try:
        occurred = datetime.fromisoformat(body.occurred_at.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(422, 'occurred_at must be ISO-8601') from None
    async with db.acquire() as conn:
        await _panel(conn, device_id, token, lock=True)
        async with conn.transaction():
            inserted = await conn.fetchval('''INSERT INTO pnl_occupancy_events(device_id,sequence,occupied,event_key,occurred_at)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT (device_id,event_key) DO NOTHING RETURNING id''', device_id, body.sequence, body.occupied, body.event_key, occurred)
    return {'device_id': device_id, 'event_key': body.event_key, 'status': 'accepted' if inserted else 'duplicate'}


@router.post('/panel/heartbeat')
async def panel_heartbeat(authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        await _panel(conn, device_id, token)
        await conn.execute('UPDATE pnl_devices SET last_heartbeat_at=now(),updated_at=now() WHERE device_id=$1', device_id)
    return {'ok': True, 'protocol': 'hcm-heartbeat-v3', 'version': 3, 'device_id': device_id}


@router.get('/panel/sonic-policy')
async def panel_sonic_policy(authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        await _panel(conn, device_id, token)
        row = await conn.fetchrow('SELECT epoch,globally_muted,expires_at FROM sonic_policy WHERE singleton=true')
    return {'device_id': device_id, **dict(row)}


@router.post('/panel/sonic-ack')
async def panel_sonic_ack(body: SonicAck, authorization: str | None = Header(default=None), x_pnl_device: str | None = Header(default=None)):
    device_id, token = _panel_headers(authorization, x_pnl_device)
    async with db.acquire() as conn:
        await _panel(conn, device_id, token)
        current = await conn.fetchval('SELECT epoch FROM sonic_policy WHERE singleton=true')
        if body.epoch != current:
            raise HTTPException(409, 'Sonic policy epoch is not current')
        await conn.execute('UPDATE pnl_devices SET last_sonic_epoch=$2,last_sonic_muted=$3,updated_at=now() WHERE device_id=$1', device_id, body.epoch, body.muted)
    return {'ok': True, 'device_id': device_id, 'epoch': body.epoch, 'muted': body.muted}


@router.get('/admin/sonic-policy')
async def admin_sonic_policy(user=Depends(require_user)):
    _admin(user)
    async with db.acquire() as conn:
        row = await conn.fetchrow('SELECT epoch,globally_muted,expires_at,updated_at FROM sonic_policy WHERE singleton=true')
    return dict(row)


class SonicPolicyUpdate(BaseModel):
    globally_muted: bool
    expires_at: datetime | None = None


@router.put('/admin/sonic-policy')
async def update_sonic_policy(body: SonicPolicyUpdate, user=Depends(require_user)):
    _admin(user)
    async with db.acquire() as conn:
        row = await conn.fetchrow('''UPDATE sonic_policy SET epoch=epoch+1,globally_muted=$1,expires_at=$2,updated_at=now()
            WHERE singleton=true RETURNING epoch,globally_muted,expires_at,updated_at''', body.globally_muted, body.expires_at)
    return dict(row)
