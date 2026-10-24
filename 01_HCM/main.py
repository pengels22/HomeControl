from __future__ import annotations
import asyncio, logging, sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .settings import settings
from . import db
from .schema_contract import check_schema
from .registry import registry
from .hvac import HVACController
from .safety import SafetyController
from .safety_relays import HCMSafetyRelayController, UnavailableLinuxSafetyInputBackend
from .rules import RulesEngine
from .notifications import notifications
from . import api
from .pnl_api import router as pnl_router
from .notification_api import router as notification_config_router
from . import storage
from .devices import command_logical

log = logging.getLogger(__name__)

async def hvac_output(name: str, value: bool):
    if value and (safety.fire_active or safety.maintenance_lockout_active):
        raise PermissionError('HVAC energization inhibited by safety')
    from .channel_registry import thermostat_output
    await thermostat_output(name, value, command_logical)

async def hvac_damper(room, open_: bool):
    if not room.damper_logical_device: return
    # Spring-open/power-close actuator: relay OFF=open, ON=closed.
    await command_logical(room.damper_logical_device, {'op':'set_relay','value':not open_})

def build_safety_relays():
    if settings.safety_input_backend == 'simulated':
        return HCMSafetyRelayController()
    if settings.safety_input_backend == 'linux':
        try:
            return HCMSafetyRelayController.from_linux(wiring_file=settings.safety_input_wiring_file)
        except Exception as exc:
            log.error('Physical safety inputs unavailable; reporting Unknown: %s', exc)
            return HCMSafetyRelayController(backend=UnavailableLinuxSafetyInputBackend())
    raise RuntimeError('HCM_SAFETY_INPUT_BACKEND must be simulated or linux')


# Linux inputs are the default. An explicit simulated setting is for development;
# an unavailable physical backend remains physical authority with Unknown inputs.
safety_relays = build_safety_relays()
hvac = HVACController(hvac_output, hvac_damper)
safety = SafetyController(hvac, safety_relays=safety_relays)
rules = RulesEngine()
api.hvac = hvac
api.safety = safety
api.safety_relays = safety_relays
api.rules_engine = rules
api.notification_service = notifications

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    async with db.acquire() as conn:
        async with conn.transaction(readonly=True):
            await check_schema(conn)
    storage.ensure_storage_layout()
    await hvac.load_from_db()
    await registry.start()
    await api.weather_service.start()
    from .bridges import bridge
    await bridge.start()
    from .integrations.runtime import runtime as integrations
    from .integrations.mock import MockProvider
    # Native NWS is authoritative.  The legacy consumer providers remain
    # importable for migration/rollback compatibility but are not loaded into
    # the active provider registry during normal HCM startup.
    from .integrations import nws, ibeacon
    from . import bluetooth
    await bluetooth.scanner.start()
    from .integrations.factory import provider_factory
    for provider_type in provider_factory.types.values():
        await integrations.registry.register(provider_type.info, enabled=False, configured=False)
    if 'internal_mock' not in integrations.entries:
        integrations.attach(MockProvider(), enabled=settings.integration_mock_enabled)
    await integrations.restore_instances()
    await integrations.start()
    from .primitives import NativePrimitives
    integrations.native_primitives = NativePrimitives(integrations.registry, timezone_name=settings.timezone, hvac=hvac, safety=safety)
    await integrations.native_primitives.start()
    from .zones import ZoneRuntime
    integrations.zone_runtime = ZoneRuntime(integrations.registry)
    await integrations.zone_runtime.start()
    from .device_events import DeviceEventRuntime
    integrations.device_event_runtime = DeviceEventRuntime(integrations.registry)
    from .automation import AutomationEngine
    integrations.automation_engine = AutomationEngine(integrations.registry, timezone_name=settings.timezone, latitude=settings.latitude, longitude=settings.longitude)
    integrations.automation_engine.zone_evaluator = integrations.zone_runtime.evaluator
    integrations.native_primitives.engine = integrations.automation_engine
    await integrations.automation_engine.start()
    storage.git_sync_manager.start()
    rule_task = asyncio.create_task(rules.run())
    hvac_task = asyncio.create_task(hvac_loop())
    alarm_task = asyncio.create_task(alarm_contact_loop())
    yield
    rules.running=False
    rule_task.cancel(); hvac_task.cancel(); alarm_task.cancel()
    if getattr(integrations, 'automation_engine', None):
        await integrations.automation_engine.stop()
    if getattr(integrations, 'native_primitives', None):
        await integrations.native_primitives.stop()
    await integrations.stop()
    await bluetooth.scanner.stop()
    await bridge.stop()
    await api.weather_service.stop()
    await storage.git_sync_manager.stop()
    await safety_relays.shutdown()
    await registry.stop(); await db.close()

async def hvac_loop():
    while True:
        await asyncio.sleep(1)
        try: await hvac.evaluate()
        except Exception: log.exception('HVAC evaluation failed')

async def alarm_contact_loop():
    while True:
        await asyncio.sleep(0.1)
        try:
            await safety.sample_fire_input_from_backend()
            await safety.sample_ac_power_from_backend()
            await safety.sample_alarm_contact_from_backend()
        except Exception:
            log.exception('Safety input monitoring failed')

app = FastAPI(title='HomeControl HCM', version='0.1.0', lifespan=lifespan)
app.include_router(api.router)
app.include_router(pnl_router)
app.include_router(notification_config_router)
from .metadata_api import router as metadata_router
app.include_router(metadata_router)
from .integrations.api import router as integration_router
app.include_router(integration_router)
from .integrations.config_api import router as integration_config_router
app.include_router(integration_config_router)
from .automation_api import router as automation_router
app.include_router(automation_router)
from .expression_api import router as expression_router
app.include_router(expression_router)
from .primitives_api import router as primitives_router
app.include_router(primitives_router)
from .ha_import_api import router as ha_import_router
app.include_router(ha_import_router)
from .ha_staging_api import router as ha_staging_router
app.include_router(ha_staging_router)
from .mapping_api import router as mapping_router
app.include_router(mapping_router)
from .zone_api import router as zone_router
app.include_router(zone_router)
from .integrations.smartthings import webhook_router as smartthings_webhook_router
app.include_router(smartthings_webhook_router)
from .bluetooth import bluetooth_router
app.include_router(bluetooth_router)
WEB_ROOT = Path(__file__).resolve().parent / 'www'
app.mount('/static', StaticFiles(directory=WEB_ROOT), name='static')

@app.get('/')
async def web_index():
    return FileResponse(WEB_ROOT / 'index.html')

@app.get('/dashboard')
@app.get('/devices')
@app.get('/devices/{path:path}')
@app.get('/service')
@app.get('/diagnostics')
@app.get('/settings')
@app.get('/ha-mappings')
@app.get('/users')
@app.get('/entities')
@app.get('/locations')
@app.get('/matter')
@app.get('/weather')
@app.get('/time')
@app.get('/safety')
async def web_app_routes():
    return FileResponse(WEB_ROOT / 'index.html')

if __name__ == '__main__':
    if '-dev' in sys.argv or '--dev' in sys.argv:
        settings.dev_mode = True
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('01_HCM.main:app', host=settings.api_host, port=settings.api_port, reload=False)
