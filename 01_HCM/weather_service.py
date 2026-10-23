"""Native, failure-isolated National Weather Service integration."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .integrations.http import ProviderHTTP
from .time_service import TimeService

log = logging.getLogger(__name__)
NWS_ROOT = 'https://api.weather.gov'
USER_AGENT = 'HomeControl/1.0 (native HCM weather service)'


def _timestamp(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get('value'), (int, float)):
        return float(value['value'])
    return None


def _condition(value: Any) -> str:
    text = str(value or '').lower()
    for word, result in (('thunder', 'thunderstorm'), ('snow', 'snow'), ('sleet', 'sleet'),
                         ('rain', 'rain'), ('shower', 'rain'), ('fog', 'fog'),
                         ('partly', 'partly_cloudy'), ('cloud', 'cloudy'), ('overcast', 'cloudy'),
                         ('clear', 'clear'), ('sun', 'clear'), ('wind', 'windy')):
        if word in text:
            return result
    return 'unknown'


@dataclass
class WeatherCurrent:
    observation_time: str | None = None
    temperature: float | None = None
    temperature_unit: str | None = None
    relative_humidity: float | None = None
    dew_point: float | None = None
    wind_speed: str | None = None
    wind_direction: int | None = None
    wind_gust: str | None = None
    barometric_pressure: float | None = None
    visibility: float | None = None
    description: str | None = None
    station_id: str | None = None
    data_age_seconds: float | None = None


@dataclass
class ForecastPeriod:
    start: str | None = None
    end: str | None = None
    name: str | None = None
    temperature: float | None = None
    temperature_unit: str | None = None
    relative_humidity: float | None = None
    precipitation_probability: float | None = None
    wind_speed: str | None = None
    wind_direction: str | None = None
    short_forecast: str | None = None
    detailed_forecast: str | None = None
    is_daytime: bool | None = None


@dataclass
class WeatherAlert:
    alert_id: str
    event: str | None = None
    headline: str | None = None
    severity: str | None = None
    urgency: str | None = None
    certainty: str | None = None
    status: str | None = None
    message_type: str | None = None
    sent: str | None = None
    effective: str | None = None
    onset: str | None = None
    expires: str | None = None
    ends: str | None = None
    area_description: list[str] | None = None
    description: str | None = None
    instruction: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    response: str | None = None
    parameters: dict | None = None


@dataclass
class WeatherHealth:
    status: str = 'unavailable'
    last_successful_current: str | None = None
    last_successful_hourly: str | None = None
    last_successful_daily: str | None = None
    last_successful_alerts: str | None = None
    last_attempted: str | None = None
    cache_age_seconds: float | None = None
    last_error: str | None = None


class NWSWeatherService:
    def __init__(self, time_service: TimeService, latitude: float | None, longitude: float | None,
                 *, client=None, cache_path: Path | None = None,
                 event_sink=None,
                 alert_interval: float = 300, current_interval: float = 600,
                 forecast_interval: float = 1800, point_interval: float = 86400):
        self.time = time_service
        self.latitude, self.longitude = latitude, longitude
        self.client = client or ProviderHTTP(timeout=10, max_bytes=2_000_000)
        self.cache_path = cache_path
        self.event_sink = event_sink
        self.intervals = {'alerts': alert_interval, 'current': current_interval,
                          'hourly': forecast_interval, 'daily': forecast_interval, 'point': point_interval}
        self.point: dict | None = None
        self.current: WeatherCurrent | None = None
        self.hourly: list[ForecastPeriod] = []
        self.daily: list[ForecastPeriod] = []
        self.alerts: dict[str, WeatherAlert] = {}
        self.health = WeatherHealth()
        self._task = None
        self._lock = asyncio.Lock()
        self._last_fetch: dict[str, float] = {}
        self._load_cache()

    def _headers(self):
        return {'User-Agent': USER_AGENT, 'Accept': 'application/geo+json'}

    def _load_cache(self):
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text())
            self.point = payload.get('point')
            self.current = WeatherCurrent(**payload['current']) if payload.get('current') else None
            self.hourly = [ForecastPeriod(**x) for x in payload.get('hourly', [])]
            self.daily = [ForecastPeriod(**x) for x in payload.get('daily', [])]
            self.alerts = {x['alert_id']: WeatherAlert(**x) for x in payload.get('alerts', [])}
            self.health = WeatherHealth(**payload.get('health', {}))
        except (OSError, ValueError, TypeError):
            log.warning('Ignoring invalid native weather cache')

    def _save_cache(self):
        if not self.cache_path:
            return
        payload = {'point': self.point, 'current': asdict(self.current) if self.current else None,
                   'hourly': [asdict(x) for x in self.hourly], 'daily': [asdict(x) for x in self.daily],
                   'alerts': [asdict(x) for x in self.alerts.values()], 'health': asdict(self.health)}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(payload, separators=(',', ':'), allow_nan=False))
            tmp.replace(self.cache_path)
        except OSError:
            log.warning('Unable to persist native weather cache')

    async def _get(self, url):
        body, _ = await self.client.json('GET', url, headers=self._headers())
        if not isinstance(body, dict):
            raise ValueError('NWS response was not an object')
        return body

    async def resolve_point(self, *, force=False):
        if self.latitude is None or self.longitude is None:
            raise ValueError('Weather latitude and longitude are not configured')
        if self.point and not force:
            return self.point
        self.point = await self._get(f'{NWS_ROOT}/points/{self.latitude},{self.longitude}')
        properties = self.point.get('properties') or {}
        self.point = {'forecast_office': properties.get('cwa'), 'grid_x': properties.get('gridX'),
                      'grid_y': properties.get('gridY'), 'forecast_url': properties.get('forecast'),
                      'hourly_url': properties.get('forecastHourly'), 'grid_data_url': properties.get('forecastGridData'),
                      'county': properties.get('county'), 'zone': properties.get('forecastZone'),
                      'observation_stations_url': properties.get('observationStations')}
        self._save_cache()
        return self.point

    @staticmethod
    def _period(raw):
        return ForecastPeriod(start=_timestamp(raw.get('startTime')), end=_timestamp(raw.get('endTime')),
            name=raw.get('name'), temperature=raw.get('temperature'), temperature_unit=raw.get('temperatureUnit'),
            relative_humidity=_number(raw.get('relativeHumidity')), precipitation_probability=_number(raw.get('probabilityOfPrecipitation')),
            wind_speed=raw.get('windSpeed'), wind_direction=raw.get('windDirection'), short_forecast=raw.get('shortForecast'),
            detailed_forecast=raw.get('detailedForecast'), is_daytime=raw.get('isDaytime'))

    async def refresh_daily(self):
        point = await self.resolve_point()
        daily = await self._get(point['forecast_url']) if point.get('forecast_url') else {}
        self.daily = [self._period(x) for x in (daily.get('properties') or {}).get('periods', [])]
        now = self.time.now_utc().isoformat().replace('+00:00', 'Z')
        self.health.last_successful_daily = now
        self._save_cache()

    async def refresh_hourly(self):
        point = await self.resolve_point()
        hourly = await self._get(point['hourly_url']) if point.get('hourly_url') else {}
        self.hourly = [self._period(x) for x in (hourly.get('properties') or {}).get('periods', [])]
        now = self.time.now_utc().isoformat().replace('+00:00', 'Z')
        self.health.last_successful_hourly = now
        self._save_cache()

    async def refresh_forecasts(self):
        """Compatibility helper; each resource remains independently callable."""
        await self.refresh_daily()
        await self.refresh_hourly()

    async def refresh_current(self):
        point = await self.resolve_point()
        stations_url = point.get('observation_stations_url')
        stations = await self._get(stations_url) if stations_url else {}
        station_url = next(iter((stations.get('observationStations') or [])), None)
        if not station_url:
            raise ValueError('NWS observation station unavailable')
        station_id = station_url.rstrip('/').split('/')[-1]
        observation = await self._get(f'{NWS_ROOT}/stations/{station_id}/observations/latest')
        props = observation.get('properties') or {}
        observed = _timestamp(props.get('timestamp'))
        age = None
        if observed:
            age = max(0.0, (self.time.now_utc() - datetime.fromisoformat(observed.replace('Z', '+00:00'))).total_seconds())
        self.current = WeatherCurrent(observation_time=observed, temperature=_number(props.get('temperature')),
            temperature_unit=(props.get('temperature') or {}).get('unitCode') if isinstance(props.get('temperature'), dict) else None,
            relative_humidity=_number(props.get('relativeHumidity')), dew_point=_number(props.get('dewpoint')),
            wind_speed=props.get('windSpeed'), wind_direction=props.get('windDirection'), wind_gust=props.get('windGust'),
            barometric_pressure=_number(props.get('barometricPressure')), visibility=_number(props.get('visibility')),
            description=props.get('textDescription'), station_id=station_id, data_age_seconds=age)
        self.health.last_successful_current = self.time.now_utc().isoformat().replace('+00:00', 'Z')
        self._save_cache()

    async def refresh_alerts(self):
        if self.latitude is None or self.longitude is None:
            raise ValueError('Weather latitude and longitude are not configured')
        body = await self._get(f'{NWS_ROOT}/alerts/active?point={self.latitude},{self.longitude}')
        active = {}
        for feature in body.get('features', []):
            props = feature.get('properties') or {}
            alert_id = feature.get('id') or props.get('id')
            if not alert_id:
                continue
            active[alert_id] = WeatherAlert(alert_id=alert_id, event=props.get('event'), headline=props.get('headline'),
                severity=props.get('severity'), urgency=props.get('urgency'), certainty=props.get('certainty'),
                status=props.get('status'), message_type=props.get('messageType'), sent=_timestamp(props.get('sent')),
                effective=_timestamp(props.get('effective')), onset=_timestamp(props.get('onset')), expires=_timestamp(props.get('expires')),
                ends=_timestamp(props.get('ends')), area_description=props.get('areaDesc'), description=props.get('description'),
                instruction=props.get('instruction'), sender=props.get('sender'), sender_name=props.get('senderName'),
                response=props.get('response'), parameters=props.get('parameters'))
        previous = self.alerts
        for alert_id, alert in active.items():
            if alert_id not in previous:
                await self._emit('weather.alert.new', asdict(alert))
            elif asdict(previous[alert_id]) != asdict(alert):
                await self._emit('weather.alert.updated', asdict(alert))
        for alert_id in set(previous) - set(active):
            await self._emit('weather.alert.expired', {'alert_id': alert_id})
        self.alerts = active
        self.health.last_successful_alerts = self.time.now_utc().isoformat().replace('+00:00', 'Z')
        self._save_cache()

    async def _emit(self, code, payload):
        if not self.event_sink:
            return
        result = self.event_sink(code, payload)
        if inspect.isawaitable(result):
            await result

    async def refresh_once(self):
        async with self._lock:
            self.health.last_attempted = self.time.now_utc().isoformat().replace('+00:00', 'Z')
            errors = []
            for name, operation in (('current', self.refresh_current), ('daily', self.refresh_daily),
                                    ('hourly', self.refresh_hourly), ('alerts', self.refresh_alerts)):
                try:
                    await operation()
                except Exception as exc:
                    errors.append(f'{name}: {type(exc).__name__}')
            self.health.last_error = '; '.join(errors) if errors else None
            has_data = bool(self.current or self.hourly or self.daily or self.alerts)
            self.health.status = 'healthy' if not errors else 'degraded' if has_data else 'unavailable'
            self.health.cache_age_seconds = self._cache_age()
            self._save_cache()
            return self.snapshot()

    def _cache_age(self):
        stamps = [self.health.last_successful_current, self.health.last_successful_hourly,
                  self.health.last_successful_daily, self.health.last_successful_alerts]
        values = [datetime.fromisoformat(x.replace('Z', '+00:00')) for x in stamps if x]
        return max(0.0, (self.time.now_utc() - min(values)).total_seconds()) if values else None

    def snapshot(self):
        current = asdict(self.current) if self.current else None
        return {'point': self.point, 'current': current, 'hourly': [asdict(x) for x in self.hourly],
                'forecast': [asdict(x) for x in self.daily], 'alerts': [asdict(x) for x in self.alerts.values()],
                'health': asdict(self.health)}

    def summary(self):
        alert_values = list(self.alerts.values())
        rank = {'Extreme': 4, 'Severe': 3, 'Moderate': 2, 'Minor': 1}
        highest = max((x.severity for x in alert_values if x.severity), key=lambda x: rank.get(x, 0), default=None)
        return {'condition': _condition(self.daily[0].short_forecast if self.daily else None),
                'temperature': self.current.temperature if self.current else None,
                'temperature_unit': self.current.temperature_unit if self.current else None,
                'humidity': self.current.relative_humidity if self.current else None,
                'active_alert_count': len(alert_values), 'highest_alert_severity': highest,
                'health': self.health.status, 'updated_at': self.health.last_attempted}

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Native weather refresh failed')
            await asyncio.sleep(min(self.intervals.values()))

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.client.close()
