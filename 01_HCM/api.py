from __future__ import annotations
import asyncio
import base64
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Header
from .models import (
    AuthChallengeIn,
    AuthVerifyIn,
    DeviceCommand,
    DeviceBindingCreateIn,
    DeviceBindingUpdateIn,
    FireStateIn,
    HvacModeIn,
    HvacSetpointIn,
    LcmChannelSettingsIn,
    LogicalDeviceCreateIn,
    LogicalDeviceUpdateIn,
    MaintenanceLockoutIn,
    SystemMaintenanceLockoutIn,
    ModuleRoleChangeIn,
    PairingKeyCreateIn,
    PairingKeyVerifyIn,
    PasswordLoginIn,
    RcmChannelNameIn,
    RcmSimulationIn,
    RmcFirmwareUpdateIn,
    RoomStateIn,
    SafetyRelayPulseIn,
    SafetyRelayStateIn,
    SimNameIn,
    UserCreateIn,
    UserPasswordChangeIn,
    UserPasswordResetIn,
    UserRoleUpdateIn,
    TouchscreenPinIn,
    TouchscreenPermissionIn,
)
from .auth import (
    create_login_challenge,
    create_pairing_key,
    create_session,
    create_user,
    change_own_password,
    list_users,
    list_pairing_keys,
    login_password,
    require_user,
    reset_user_password,
    update_user_role,
    verify_login_challenge,
    verify_pairing_key,
    enroll_touchscreen_pin,
    disable_touchscreen_pin,
    set_touchscreen_permission,
    revoke_touchscreen_sessions,
    authenticate_touchscreen_device,
    unlock_touchscreen,
    require_touchscreen_session,
    touchscreen_device_permits_logical,
    revoke_touchscreen_session,
)
from .devices import MaintenanceLockedError, command_logical, set_maintenance_lockout
from .hvac import Mode
from . import management
from . import role_switching
from .settings import settings
from . import storage
from .updater import updater
from .registry import registry

router = APIRouter(prefix='/api/v1')
hvac = None
safety = None
safety_relays = None

@router.get('/health')
async def health():
    payload = {'ok': True}
    if safety is not None:
        payload['fire_life_safety'] = safety.status_payload()
        payload['safety_inputs'] = {
            'fire_alarm_s': payload['fire_life_safety'].get('fire_alarm_s'),
            'fire_alarm_P': payload['fire_life_safety'].get('fire_alarm_P'),
        }
    else:
        payload['fire_life_safety'] = {'status': 'Unavailable', 'source': 'hcm_safety_controller'}
        payload['safety_inputs'] = {'fire_alarm_s': {'state': 'unknown'}, 'fire_alarm_P': {'state': 'unknown'}}
    return payload

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

@router.get('/auth/users')
async def auth_list_users(user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return {'users': await list_users(), 'roles': ['ADMIN', 'READONLY']}

@router.post('/auth/users')
async def auth_create_user(body: UserCreateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return await create_user(body.username, body.password, body.role)

@router.patch('/auth/users/{username}/role')
async def auth_update_user_role(username: str, body: UserRoleUpdateIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return await update_user_role(username, body.role)

@router.post('/auth/users/{username}/password')
async def auth_reset_user_password(username: str, body: UserPasswordResetIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    return await reset_user_password(username, body.password)

@router.post('/auth/password')
async def auth_change_password(body: UserPasswordChangeIn, user=Depends(require_user)):
    return await change_own_password(user['user'], body.current_password, body.new_password)

@router.post('/auth/users/{username}/touchscreen-pin')
async def touchscreen_pin_enroll(username: str, body: TouchscreenPinIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return await enroll_touchscreen_pin(username, body.pin, body.permission)

@router.delete('/auth/users/{username}/touchscreen-pin')
async def touchscreen_pin_disable(username: str, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return await disable_touchscreen_pin(username)

@router.patch('/auth/users/{username}/touchscreen-permission')
async def touchscreen_permission_update(username: str, body: TouchscreenPermissionIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return await set_touchscreen_permission(username, body.permission)

@router.post('/auth/users/{username}/touchscreen-sessions/revoke')
async def touchscreen_sessions_revoke(username: str, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return await revoke_touchscreen_sessions(username)

@router.post('/touchscreen/unlock')
async def touchscreen_unlock(
    body: TouchscreenPinIn,
    x_homecontrol_touchscreen_id: str | None = Header(default=None),
    x_homecontrol_touchscreen_token: str | None = Header(default=None),
):
    return await unlock_touchscreen(body.pin, x_homecontrol_touchscreen_id or '', x_homecontrol_touchscreen_token or '')

@router.post('/touchscreen/lock')
async def touchscreen_lock(
    x_homecontrol_touchscreen_id: str | None = Header(default=None),
    x_homecontrol_touchscreen_session: str | None = Header(default=None),
):
    await require_touchscreen_session(x_homecontrol_touchscreen_session or '', x_homecontrol_touchscreen_id or '')
    return await revoke_touchscreen_session(x_homecontrol_touchscreen_session or '', x_homecontrol_touchscreen_id or '')

@router.get('/touchscreen/session')
async def touchscreen_session(
    x_homecontrol_touchscreen_id: str | None = Header(default=None),
    x_homecontrol_touchscreen_session: str | None = Header(default=None),
):
    session = await require_touchscreen_session(x_homecontrol_touchscreen_session or '', x_homecontrol_touchscreen_id or '')
    return {"ok": True, **session}

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

@router.get('/dashboard/status')
async def dashboard_status(user=Depends(require_user)):
    return await management.dashboard_status()

@router.get('/touchscreen/state')
async def touchscreen_state(
    module_identifier: str,
    role: str | None = None,
    authorization: str | None = Header(default=None),
    x_homecontrol_touchscreen_id: str | None = Header(default=None),
    x_homecontrol_touchscreen_token: str | None = Header(default=None),
):
    if authorization:
        await require_user(authorization)
    else:
        device = await authenticate_touchscreen_device(x_homecontrol_touchscreen_id or '', x_homecontrol_touchscreen_token or '')
        permitted = device.get('permitted_module_ids') or []
        if permitted and module_identifier not in permitted:
            raise HTTPException(403, 'touchscreen is not permitted to read this module')
        if not permitted:
            raise HTTPException(403, 'touchscreen has no permitted module scope')
    try:
        return await management.get_touchscreen_state(module_identifier, role=role)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc

@router.get('/settings/network')
async def settings_network(user=Depends(require_user)):
    return await management.settings_network()

@router.get('/settings/git')
async def settings_git(user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return storage.get_git_settings()

@router.put('/settings/git')
async def settings_git_update(body: dict, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return storage.update_git_settings(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post('/settings/github/connect')
async def settings_github_connect(body: dict, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await storage.connect_github(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.delete('/settings/github')
async def settings_github_disconnect(user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    return storage.disconnect_github()

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

@router.get('/device-admin/{identifier}')
async def device_admin(identifier: str, user=Depends(require_user)):
    try:
        return await management.get_device_admin(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/device-admin/{identifier}/rcm-channels')
async def device_admin_rcm_channels(identifier: str, user=Depends(require_user)):
    try:
        return await management.get_rcm_channels(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.patch('/device-admin/{identifier}/rcm-channels/{channel}/name')
async def device_admin_rcm_channel_name(
    identifier: str,
    channel: str,
    body: RcmChannelNameIn,
    user=Depends(require_user),
):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await management.update_rcm_channel_name(
            identifier,
            channel,
            name=body.name,
            actor=user['user'],
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post('/device-admin/{identifier}/rcm-channels/{channel}/simulation')
async def device_admin_rcm_channel_simulation(
    identifier: str,
    channel: str,
    body: RcmSimulationIn,
    user=Depends(require_user),
):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await management.simulate_rcm_channel(
            identifier,
            channel,
            action=body.action,
            value=body.value,
            actor=user['user'],
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/device-admin/{identifier}/lcm-channels')
async def device_admin_lcm_channels(identifier: str, user=Depends(require_user)):
    try:
        return await management.get_lcm_channels(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.patch('/device-admin/{identifier}/lcm-channels/{channel}/settings')
async def device_admin_lcm_channel_settings(
    identifier: str,
    channel: str,
    body: LcmChannelSettingsIn,
    user=Depends(require_user),
):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await management.update_lcm_channel_settings(
            identifier,
            channel,
            name=body.name,
            emergency_lighting=body.emergency_lighting,
            max_intensity=body.max_intensity,
            fade_seconds=body.fade_seconds,
            actor=user['user'],
        )
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/device-admin/{identifier}/sim-dashboard')
async def device_admin_sim_dashboard(identifier: str, user=Depends(require_user)):
    try:
        return await management.get_sim_dashboard(identifier)
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.patch('/device-admin/{identifier}/sim-rmcs/{rmc_id}/settings')
async def device_admin_sim_rmc_settings(
    identifier: str,
    rmc_id: str,
    body: SimNameIn,
    user=Depends(require_user),
):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await management.update_sim_rmc_name(identifier, rmc_id, name=body.name, actor=user['user'])
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.patch('/device-admin/{identifier}/sim-analog-inputs/{channel}/settings')
async def device_admin_sim_analog_settings(
    identifier: str,
    channel: str,
    body: SimNameIn,
    user=Depends(require_user),
):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await management.update_sim_analog_name(identifier, channel, name=body.name, actor=user['user'])
    except management.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get('/module-roles')
async def module_roles(user=Depends(require_user)):
    return {'modules': await role_switching.list_role_managed_modules(), 'roles': list(role_switching.ALLOWED_ROLES)}

@router.get('/module-role-transitions/{operation_id}')
async def module_role_transition(operation_id: str, user=Depends(require_user)):
    try:
        return await role_switching.get_transition(operation_id)
    except role_switching.RoleSwitchNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

@router.post('/modules/{device_id}/role')
async def module_role_change(device_id: str, body: ModuleRoleChangeIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    if not body.confirm:
        raise HTTPException(400, 'explicit confirmation is required')
    try:
        normalized_device_id = role_switching.normalize_device_id(device_id)
        async with registry._connections_lock:
            control_session = registry.connections.get(normalized_device_id)
        if control_session is None or control_session.device_id != normalized_device_id:
            raise HTTPException(409, 'module has no authenticated online control session')
        transition = await role_switching.create_transition(
            device_id=normalized_device_id,
            requested_role=body.requested_role,
            actor=user['user'],
            control_session_key=control_session.connection_key or '',
        )
        await role_switching.mark_sent(transition['operation_id'])
        try:
            ack = await control_session.command(
                {
                    **transition['command_payload'],
                    'operation_id': transition['operation_id'],
                },
                request_id=transition['operation_id'],
                timeout=10.0,
            )
        except Exception as exc:
            await role_switching.mark_failed(transition['operation_id'], str(exc))
            raise HTTPException(504, 'module did not acknowledge role-change request') from exc
        return await role_switching.mark_acknowledged(transition['operation_id'], ack)
    except role_switching.RoleSwitchError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post('/modules/{device_id}/role/reconcile')
async def reconcile_module_role(device_id: str, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    try:
        return await role_switching.reconcile_confirmed_registration(device_id, user['user'])
    except role_switching.RoleSwitchError as exc:
        raise HTTPException(409, str(exc)) from exc

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
            room_id=body.room_id if 'room_id' in body.model_fields_set else management.UNSET,
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
    except management.ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
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
async def device_command(
    body: DeviceCommand,
    authorization: str | None = Header(default=None),
    x_homecontrol_touchscreen_id: str | None = Header(default=None),
    x_homecontrol_touchscreen_session: str | None = Header(default=None),
):
    if authorization:
        user = await require_user(authorization)
        if user['role'] != 'ADMIN':
            raise HTTPException(403)
    else:
        session = await require_touchscreen_session(x_homecontrol_touchscreen_session or '', x_homecontrol_touchscreen_id or '', refresh=True)
        if session['permission'] not in {'CONTROL', 'ADMIN'}:
            raise HTTPException(403, 'touchscreen permission does not allow control')
        if not await touchscreen_device_permits_logical(session['device_id'], body.logical_name):
            raise HTTPException(403, 'touchscreen is not permitted to control this logical device')
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
    if safety is None:
        raise HTTPException(503, 'safety controller is not configured')
    if safety.physical_fire_input_authoritative():
        raise HTTPException(409, 'physical fire input is authoritative; simulation injection is unavailable')
    await safety.set_fire(body.active, source='simulation')
    return {'ok': True, 'fire_active': safety.fire_active}

@router.post('/safety/maintenance-lockout')
async def maintenance_lockout(body: MaintenanceLockoutIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN': raise HTTPException(403)
    try:
        result = await set_maintenance_lockout(body.logical_name, body.active)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'maintenance_locked': body.active, **result}

@router.get('/safety/system-maintenance-lockout')
async def get_system_maintenance_lockout(user=Depends(require_user)):
    if safety is None:
        raise HTTPException(503, 'safety controller is not configured')
    return {'ok': True, 'scope': 'system_life_safety', 'maintenance_lockout_active': safety.maintenance_lockout_active, 'fire_active': safety.fire_active, 'status': safety.status_payload()}

@router.post('/safety/system-maintenance-lockout')
async def set_system_maintenance_lockout(body: SystemMaintenanceLockoutIn, user=Depends(require_user)):
    if user['role'] != 'ADMIN':
        raise HTTPException(403)
    if safety is None:
        raise HTTPException(503, 'safety controller is not configured')
    await safety.set_maintenance_lockout(body.active)
    return {'ok': True, 'scope': 'system_life_safety', 'maintenance_lockout_active': safety.maintenance_lockout_active, 'fire_active': safety.fire_active, 'status': safety.status_payload()}

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
