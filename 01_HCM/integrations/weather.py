"""Provider-neutral weather values used by NWS and OpenWeatherMap."""
from dataclasses import dataclass,asdict
from .. import db

async def record_poll(context,success,error=None):
    if not context.instance_id: return
    async with db.acquire() as conn:
        if success:
            await conn.execute("UPDATE integration_instances SET last_attempt=now(),last_successful_poll=now(),consecutive_failures=0,backoff_until=NULL,stale=false,last_error=NULL WHERE instance_id=$1",context.instance_id)
        else:
            await conn.execute("UPDATE integration_instances SET last_attempt=now(),consecutive_failures=consecutive_failures+1,stale=(consecutive_failures+1 >= 3),last_error=$2 WHERE instance_id=$1",context.instance_id,str(error or 'poll failed')[:120])

CONDITIONS={'clear','partly_cloudy','cloudy','fog','rain','heavy_rain','snow','sleet','thunderstorm','windy','unknown'}
def normalize_condition(value):
    text=str(value or '').lower()
    if 'thunder' in text: return 'thunderstorm'
    if 'snow' in text: return 'snow'
    if 'sleet' in text or 'ice' in text: return 'sleet'
    if 'heavy rain' in text or 'extreme rain' in text: return 'heavy_rain'
    if 'rain' in text or 'shower' in text: return 'rain'
    if 'fog' in text or 'mist' in text: return 'fog'
    if 'partly' in text: return 'partly_cloudy'
    if 'cloud' in text or 'overcast' in text: return 'cloudy'
    if 'clear' in text or 'sun' in text: return 'clear'
    if 'wind' in text: return 'windy'
    return 'unknown'

@dataclass
class WeatherState:
    condition: str|None=None; temperature: float|None=None; apparent_temperature: float|None=None
    humidity: float|None=None; pressure: float|None=None; wind_speed: float|None=None
    wind_direction: str|None=None; precipitation_probability: float|None=None; precipitation: float|None=None
    forecast: list|None=None; alerts: list|None=None; provider: str|None=None
    def as_dict(self): return {k:v for k,v in asdict(self).items() if v is not None}

@dataclass
class ForecastEntry:
    start: str|None=None; end: str|None=None; condition: str='unknown'; temperature: float|None=None
    apparent_temperature: float|None=None; humidity: float|None=None; pressure: float|None=None
    wind_speed: float|None=None; wind_direction: str|None=None; precipitation_probability: float|None=None
    precipitation: float|None=None; cloud_coverage: float|None=None
    def as_dict(self): return asdict(self)
