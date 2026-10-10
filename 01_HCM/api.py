from __future__ import annotations
import asyncio
import base64
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from .models import (
    AuthChallengeIn,
    AuthVerifyIn,
    DeviceCommand,
    DeviceBindingCreateIn,
    DeviceBindingUpdateIn,
    FireStateIn,
    HvacModeIn,
    HvacSetpointIn,
    LogicalDeviceCreateIn,
    LogicalDeviceUpdateIn,
    MaintenanceLockoutIn,
    PairingKeyCreateIn,
    PairingKeyVerifyIn,
    PasswordLoginIn,
    RmcFirmwareUpdateIn,
    RoomStateIn,
    SafetyRelayPulseIn,
    SafetyRelayStateIn,
    UserCreateIn,
)
from .auth import (
    create_login_challenge,
    create_pairing_key,
    create_session,
    create_user,
    list_pairing_keys,
    login_password,
    require_user,
    verify_login_challenge,
    verify_pairing_key,
)
from .devices import MaintenanceLockedError, command_logical, set_maintenance_lockout
from .hvac import Mode
from . import management
from .settings import settings
from .updater import updater

router = APIRouter(prefix='/api/v1')
hvac = None
safety = None
safety_relays = None

@router.get('/health')
async def health(): return {'ok': True}

@router.post('/auth/dev-session')
async def dev_session():
    # Local-development bootstrap only. Disable/remove before production deployment.
    if not settings.dev_mode:
        raise HTTPException(404)
    return {'token': create_session('local-admin','ADMIN')}

@router.post('/auth/login')
async def auth_login(body: PasswordLoginIn):
    return {'token': await login_password(body.username, body.password)}

@router.get('/auth/session')
async def auth_session(user=Depends(require_user)):
    return user

@router.post('/auth/users')
async def auth_create_user(body: UserCreateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return await create_user(body.username, body.password, body.role)

@router.post('/auth/passkey/challenge')
async def auth_challenge(body: AuthChallengeIn):
    return await create_login_challenge(body.username)

@router.post('/auth/passkey/verify')
async def auth_verify(body: AuthVerifyIn):
    return {'token': await verify_login_challenge(body.username, body.challenge, body.assertion)}

@router.post('/pairing-keys')
async def pairing_create(body: PairingKeyCreateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return await create_pairing_key(
        body.label,
        body.target_type,
        user['user'],
        body.ttl_minutes,
        body.metadata,
    )

@router.get('/pairing-keys')
async def pairing_list(user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return {'pairing_keys': await list_pairing_keys()}

@router.post('/pairing-keys/verify')
async def pairing_verify(body: PairingKeyVerifyIn):
    return await verify_pairing_key(body.pairing_key, body.used_by)

@router.get('/hvac')
async def get_hvac(user=Depends(require_user)):
    s = hvac.state
    return {'mode': s.mode.value, 'setpoint_f': s.setpoint_f, 'average_f': hvac.average_temperature(), 'fan':s.fan,'heat':s.heat,'cool':s.cool}

@router.get('/modules')
async def modules(user=Depends(require_user)):
    return {'modules': await management.list_modules()}

@router.get('/modules/{identifier}')
async def module_detail(identifier: str, user=Depends(require_user)):
    try:
        return await management.get_module(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/modules/{identifier}/capabilities')
async def module_capabilities(identifier: str, user=Depends(require_user)):
    try:
        module = await management.get_module(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'module': module['hostname'], 'capabilities': module['capabilities']}

@router.get('/logical-devices')
async def logical_devices(user=Depends(require_user)):
    return {'logical_devices': await management.list_logical_devices()}

@router.post('/logical-devices')
async def logical_device_create(body: LogicalDeviceCreateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        return await management.create_logical_device(
            logical_name=body.logical_name,
            device_class=body.device_class,
            room_id=body.room_id,
            enabled=body.enabled,
            metadata=body.metadata,
            actor=user['user'],
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, 'logical device already exists') from exc

@router.patch('/logical-devices/{logical_name}')
async def logical_device_update(logical_name: str, body: LogicalDeviceUpdateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        return await management.update_logical_device(
            logical_name,
            actor=user['user'],
            new_logical_name=body.logical_name,
            device_class=body.device_class,
            room_id=body.room_id,
            enabled=body.enabled,
            maintenance_locked=body.maintenance_locked,
            metadata=body.metadata,
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, 'logical device update conflicts with existing data') from exc

@router.get('/device-bindings')
async def device_bindings(user=Depends(require_user)):
    return {'device_bindings': await management.list_bindings()}

@router.post('/device-bindings')
async def device_binding_create(body: DeviceBindingCreateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        return await management.create_binding(
            logical_name=body.logical_name,
            module_identifier=body.module_identifier,
            channel=body.channel,
            binding_type=body.binding_type,
            enabled=body.enabled,
            metadata=body.metadata,
            actor=user['user'],
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, 'device binding already exists') from exc

@router.patch('/device-bindings/{binding_id}')
async def device_binding_update(binding_id: int, body: DeviceBindingUpdateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        return await management.update_binding(
            binding_id,
            actor=user['user'],
            channel=body.channel,
            binding_type=body.binding_type,
            enabled=body.enabled,
            metadata=body.metadata,
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, 'device binding update conflicts with existing data') from exc

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

@router.post('/firmware/rmc/update')
async def rmc_firmware_update(body: RmcFirmwareUpdateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        firmware_image = base64.b64decode(body.firmware_image_b64.encode('ascii'), validate=True)
    except Exception as exc:
        raise HTTPException(400, 'firmware_image_b64 is not valid base64') from exc
    try:
        return await updater.update_rmc_via_sim(
            target_rmc_id=body.target_rmc_id,
            sim_hostname=body.sim_hostname,
            can_interface=body.can_interface,
            node_id=body.node_id,
            firmware_image=firmware_image,
            firmware_version=body.firmware_version,
            hardware_revision=body.hardware_revision,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ConnectionError as exc:
        raise HTTPException(503, str(exc))

@router.post('/safety/fire')
async def fire(body: FireStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    await safety.set_fire(body.active)
    return {'ok': True, 'fire_active': safety.fire_active}

@router.post('/safety/maintenance-lockout')
async def maintenance_lockout(body: MaintenanceLockoutIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        result = await set_maintenance_lockout(body.logical_name, body.active)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'maintenance_locked': body.active, **result}

@router.get('/safety/hcm-relays')
async def safety_hcm_relays(user=Depends(require_user)):
    if safety_relays is None:
        raise HTTPException(503, 'HCM safety relay controller is not configured')
    return safety_relays.status()

@router.post('/safety/hcm-relays/pulse')
async def safety_hcm_relay_pulse(body: SafetyRelayPulseIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    if safety_relays is None:
        raise HTTPException(503, 'HCM safety relay controller is not configured')
    try:
        return await safety_relays.pulse(body.relay, body.duration_ms)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))

@router.put('/safety/hcm-relays')
async def safety_hcm_relay_state(body: SafetyRelayStateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    if safety_relays is None:
        raise HTTPException(503, 'HCM safety relay controller is not configured')
    try:
        return await safety_relays.set_output(body.relay, body.active)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
