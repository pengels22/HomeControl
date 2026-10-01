from __future__ import annotations
import asyncio, logging, sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .settings import settings
from . import db
from .registry import registry
from .hvac import HVACController
from .safety import SafetyController
from .rules import RulesEngine
from . import api
from .devices import command_logical

log = logging.getLogger(__name__)

async def hvac_output(name: str, value: bool):
    # These logical devices are expected to be bound in PostgreSQL.
    # FAN/COOL/HEAT map to the relay outputs switching R->G, R->Y, R->W.
    logical = {'FAN':'HVAC Fan Call','COOL':'HVAC Cool Call','HEAT':'HVAC Heat Call'}[name]
    await command_logical(logical, {'op':'set_relay','value':value})

async def hvac_damper(room, open_: bool):
    if not room.damper_logical_device: return
    # Spring-open/power-close actuator: relay OFF=open, ON=closed.
    await command_logical(room.damper_logical_device, {'op':'set_relay','value':not open_})

hvac = HVACController(hvac_output, hvac_damper)
safety = SafetyController(hvac)
rules = RulesEngine()
api.hvac = hvac
api.safety = safety

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await hvac.load_from_db()
    await registry.start()
    rule_task = asyncio.create_task(rules.run())
    hvac_task = asyncio.create_task(hvac_loop())
    yield
    rules.running=False
    rule_task.cancel(); hvac_task.cancel()
    await registry.stop(); await db.close()

async def hvac_loop():
    while True:
        await asyncio.sleep(1)
        try: await hvac.evaluate()
        except Exception: log.exception('HVAC evaluation failed')

app = FastAPI(title='HomeControl HCM', version='0.1.0', lifespan=lifespan)
app.include_router(api.router)
WEB_ROOT = Path(__file__).resolve().parent / 'www'
app.mount('/static', StaticFiles(directory=WEB_ROOT), name='static')

@app.get('/')
async def web_index():
    return FileResponse(WEB_ROOT / 'index.html')

if __name__ == '__main__':
    if '-dev' in sys.argv or '--dev' in sys.argv:
        settings.dev_mode = True
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('01_HCM.main:app', host=settings.api_host, port=settings.api_port, reload=False)
