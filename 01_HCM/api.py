from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from .models import AuthChallengeIn, AuthVerifyIn, RoomStateIn, HvacSetpointIn, HvacModeIn, DeviceCommand, FireStateIn
from .auth import create_login_challenge, require_user, create_session, verify_login_challenge
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

@router.post('/auth/passkey/challenge')
async def auth_challenge(body: AuthChallengeIn):
    return await create_login_challenge(body.username)

@router.post('/auth/passkey/verify')
async def auth_verify(body: AuthVerifyIn):
    return {'token': await verify_login_challenge(body.username, body.challenge, body.assertion)}

@router.get('/hvac')
async def get_hvac(user=Depends(require_user)):
    s = hvac.state
    return {'mode': s.mode.value, 'setpoint_f': s.setpoint_f, 'average_f': hvac.average_temperature(), 'fan':s.fan,'heat':s.heat,'cool':s.cool}

@router.put('/hvac/mode')
async def set_mode(body: HvacModeIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    hvac.state.mode = Mode(body.mode)
    await hvac.persist_state()
    if hvac.state.mode == Mode.OFF: await hvac.force_off()
    else: await hvac.evaluate()
    return {'ok': True, 'mode': hvac.state.mode.value}

@router.put('/hvac/setpoint')
async def set_setpoint(body: HvacSetpointIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    hvac.state.setpoint_f = body.setpoint_f
    await hvac.persist_state()
    await hvac.evaluate()
    return {'ok': True, 'setpoint_f': hvac.state.setpoint_f}

@router.put('/hvac/room')
async def room(body: RoomStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    from .hvac import RoomReading
    hvac.rooms[body.room] = RoomReading(**body.model_dump())
    await hvac.persist_room(hvac.rooms[body.room])
    await hvac.evaluate()
    return {'ok': True, 'average_f': hvac.average_temperature()}

@router.post('/device/command')
async def device_command(body: DeviceCommand, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try: return await command_logical(body.logical_name, body.command, source='user')
    except KeyError as exc: raise HTTPException(404, str(exc))
    except MaintenanceLockedError as exc: raise HTTPException(423, str(exc))
    except ConnectionError as exc: raise HTTPException(503, str(exc))

@router.post('/safety/fire')
async def fire(body: FireStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    await safety.set_fire(body.active)
    return {'ok': True, 'fire_active': safety.fire_active}
