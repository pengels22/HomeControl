from importlib import import_module
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .auth import require_user
from . import db, channel_registry as registry

router = APIRouter(prefix='/api/v1')


async def admin(user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return user


class RoomIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    area_id: int | None = Field(default=None, ge=1)


class AreaIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class PanelRooms(BaseModel):
    model_config = ConfigDict(extra='forbid')
    room_ids: list[int] = Field(default_factory=list, max_length=100)
    primary_room_id: int | None = None


@router.get('/areas')
async def areas(user=Depends(require_user)):
    return await registry.area_list()


@router.post('/areas')
async def create_area(body: AreaIn, user=Depends(admin)):
    try:
        async with db.acquire() as conn:
            return dict(await conn.fetchrow('INSERT INTO hcm_areas(name,enabled) VALUES($1,$2) RETURNING *', body.name, body.enabled))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, 'Area name already exists') from None
    except asyncpg.CheckViolationError:
        raise HTTPException(422, 'Invalid Area name') from None


@router.put('/areas/{area_id}')
async def update_area(area_id: int, body: AreaIn, user=Depends(admin)):
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow('UPDATE hcm_areas SET name=$2,enabled=$3 WHERE id=$1 RETURNING *', area_id, body.name, body.enabled)
        if not row:
            raise HTTPException(404)
        return dict(row)
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, 'Area name already exists') from None
    except asyncpg.CheckViolationError:
        raise HTTPException(422, 'Invalid Area name') from None


@router.delete('/areas/{area_id}')
async def delete_area(area_id: int, user=Depends(admin)):
    # Preserve room associations and stable Area identity.
    async with db.acquire() as conn:
        row = await conn.fetchrow('UPDATE hcm_areas SET enabled=false WHERE id=$1 RETURNING *', area_id)
    if not row:
        raise HTTPException(404)
    return dict(row)


@router.get('/rooms')
async def rooms(user=Depends(require_user)):
    return await registry.room_list()


@router.post('/rooms')
async def create_room(body: RoomIn, user=Depends(admin)):
    try:
        async with db.acquire() as conn:
            return dict(await conn.fetchrow('INSERT INTO rooms(name,enabled,area_id) VALUES($1,$2,$3) RETURNING *', body.name, body.enabled, body.area_id))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, 'Room name already exists') from None
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(422, 'Unknown Area') from None


@router.put('/rooms/{room_id}')
async def update_room(room_id: int, body: RoomIn, user=Depends(admin)):
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow('''UPDATE rooms SET name=$2,enabled=$3,
                area_id=CASE WHEN $4 THEN $5 ELSE area_id END WHERE id=$1 RETURNING *''',
                room_id, body.name, body.enabled, 'area_id' in body.model_fields_set, body.area_id)
            if not row:
                raise HTTPException(404)
            result = dict(row)
        await refresh_hvac_rooms()
        return result
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, 'Room name already exists') from None
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(422, 'Unknown Area') from None


@router.delete('/rooms/{room_id}')
async def delete_room(room_id: int, user=Depends(admin)):
    # Soft deletion preserves HVAC history, channel and PNL associations.
    async with db.acquire() as conn:
        row = await conn.fetchrow('UPDATE rooms SET enabled=false WHERE id=$1 RETURNING *', room_id)
    if not row:
        raise HTTPException(404)
    await refresh_hvac_rooms()
    return dict(row)


async def refresh_hvac_rooms():
    from . import api
    if api.hvac is not None:
        await api.hvac.load_from_db()


@router.get('/channels')
async def channels(identifier: str | None = None, user=Depends(require_user)):
    return await registry.channels(identifier)


@router.get('/entities')
async def entities(identifier: str | None = None, module: str | None = None,
                   room: str | None = None, area: str | None = None,
                   capability: str | None = None, availability: str | None = None,
                   user=Depends(require_user)):
    from .entities import list_channel_entities
    from .entities import filter_entities
    rows = await list_channel_entities(identifier)
    return filter_entities(rows, module=module, room=room, area=area,
                           capability=capability, availability=availability)


@router.get('/entities/{entity_id}')
async def entity(entity_id: str, user=Depends(require_user)):
    from .entities import list_channel_entities
    rows = await list_channel_entities()
    match = next((row for row in rows if row['entity_id'] == entity_id), None)
    if match is None:
        raise HTTPException(404, 'Entity not found')
    return match


@router.patch('/channels/{channel_id}')
async def update_channel(channel_id: int, body: dict, user=Depends(admin)):
    try:
        return await registry.update_channel(channel_id, body, user['user'])
    except KeyError:
        raise HTTPException(404) from None
    except (ValueError, asyncpg.CheckViolationError, asyncpg.ForeignKeyViolationError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/modules/{identifier}/rooms')
async def panel_rooms(identifier: str, user=Depends(require_user)):
    async with db.acquire() as conn:
        return [dict(r) for r in await conn.fetch('''SELECT p.room_id,p.is_primary FROM pnl_rooms p
            JOIN modules m ON m.id=p.module_id WHERE m.device_id=$1 OR m.hostname=$1''', identifier)]


@router.put('/modules/{identifier}/rooms')
async def set_panel_rooms(identifier: str, body: PanelRooms, user=Depends(admin)):
    if len(set(body.room_ids)) != len(body.room_ids) or (body.primary_room_id is not None and body.primary_room_id not in body.room_ids):
        raise HTTPException(422, 'Primary room must belong to the unique room_ids list')
    try:
        async with db.acquire() as conn:
            async with conn.transaction():
                module = await conn.fetchrow("SELECT id FROM modules WHERE (device_id=$1 OR hostname=$1) AND module_type='PNL' FOR UPDATE", identifier)
                if not module:
                    raise HTTPException(404)
                await conn.execute('DELETE FROM pnl_rooms WHERE module_id=$1', module['id'])
                for room_id in body.room_ids:
                    await conn.execute('INSERT INTO pnl_rooms(module_id,room_id,is_primary) VALUES($1,$2,$3)', module['id'], room_id, room_id == body.primary_room_id)
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(422, 'Unknown room') from None
    return {'ok': True}


@router.get('/modules/{identifier}/room-controls')
async def room_controls(identifier: str, user=Depends(require_user)):
    return await registry.pnl_controls(identifier)


@router.get('/bridges')
async def bridge_status(user=Depends(require_user)):
    from .bridges import bridge
    return await bridge.status()


class BridgeSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    enabled: bool = False
    host: str = Field(default='', max_length=253, pattern=r'^[A-Za-z0-9.:-]*$')
    port: int = Field(default=8883, ge=1, le=65535)
    tls: bool = True


@router.put('/bridges/{bridge_name}/settings')
async def bridge_settings(bridge_name: str, body: BridgeSettings, user=Depends(admin)):
    import json
    if bridge_name not in {'mqtt', 'matter'}:
        raise HTTPException(404)
    if bridge_name == 'mqtt' and body.enabled and not body.host:
        raise HTTPException(422, 'An MQTT broker hostname is required')
    settings = body.model_dump() if bridge_name == 'mqtt' else {'enabled': body.enabled}
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute('''INSERT INTO bridge_settings(bridge,settings) VALUES($1,$2::jsonb)
                ON CONFLICT(bridge) DO UPDATE SET settings=EXCLUDED.settings,updated_at=now()''',bridge_name,json.dumps(settings))
            await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,'bridge_settings_updated','bridge',$2)",user['user'],bridge_name)
    from .bridges import bridge
    bridge.changed.set()
    return settings
