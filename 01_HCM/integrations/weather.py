"""Provider-neutral weather values used by NWS and OpenWeatherMap."""
from dataclasses import dataclass,asdict

@dataclass
class WeatherState:
    condition: str|None=None; temperature: float|None=None; apparent_temperature: float|None=None
    humidity: float|None=None; pressure: float|None=None; wind_speed: float|None=None
    wind_direction: str|None=None; precipitation_probability: float|None=None; precipitation: float|None=None
    forecast: list|None=None; alerts: list|None=None; provider: str|None=None
    def as_dict(self): return {k:v for k,v in asdict(self).items() if v is not None}
