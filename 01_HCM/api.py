from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from .models import RoomStateIn, HvacSetpointIn, HvacModeIn, DeviceCommand, FireStateIn
from .auth import require_user, create_session
from .devices import MaintenanceLockedError, command_logical
from .hvac import Mode
from .settings import settings

router = APIRouter(prefix='/api/v1')
hvac = None
safety = None

@router.get('/health')
async def health(): return {'ok': True}

@router.post('/auth/dev-session')
async def dev_session():
    # Local-development bootstrap only. Disable/remove before production deployment.
    if not settings.dev_mode:
        raise HTTPException(404)
    return {'token': create_session('local-admin','ADMIN')}

@router.get('/hvac')
async def get_hvac(user=Depends(require_user)):
    s = hvac.state
    return {'mode': s.mode.value, 'setpoint_f': s.setpoint_f, 'average_f': hvac.average_temperature(), 'fan':s.fan,'heat':s.heat,'cool':s.cool}

@router.put('/hvac/mode')
async def set_mode(body: HvacModeIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    hvac.state.mode = Mode(body.mode)
    if hvac.state.mode == Mode.OFF: await hvac.force_off()
    else: await hvac.evaluate()
    return {'ok': True, 'mode': hvac.state.mode.value}

@router.put('/hvac/setpoint')
async def set_setpoint(body: HvacSetpointIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    hvac.state.setpoint_f = body.setpoint_f
    await hvac.evaluate()
    return {'ok': True, 'setpoint_f': hvac.state.setpoint_f}

@router.put('/hvac/room')
async def room(body: RoomStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    from .hvac import RoomReading
    hvac.rooms[body.room] = RoomReading(**body.model_dump())
    await hvac.evaluate()
    return {'ok': True, 'average_f': hvac.average_temperature()}

@router.post('/device/command')
async def device_command(body: DeviceCommand, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try: return await command_logical(body.logical_name, body.command)
    except KeyError as exc: raise HTTPException(404, str(exc))
    except MaintenanceLockedError as exc: raise HTTPException(423, str(exc))
    except ConnectionError as exc: raise HTTPException(503, str(exc))

@router.post('/safety/fire')
async def fire(body: FireStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    await safety.set_fire(body.active)
    return {'ok': True, 'fire_active': safety.fire_active}
