import asyncio
from datetime import datetime, timezone
from importlib import import_module

import pytest


weather = import_module('02_HCM.weather_service')
time_mod = import_module('02_HCM.time_service')


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    async def json(self, method, url, **kwargs):
        self.urls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value, 200

    async def close(self):
        pass


def service(responses):
    clock = time_mod.TimeService('America/Detroit', clock=lambda: datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    return weather.NWSWeatherService(clock, 42.3, -83.0, client=FakeClient(responses))


@pytest.mark.asyncio
async def test_point_lookup_canonicalizes_coordinates_and_recovers_incomplete_cache():
    point_url = 'https://api.weather.gov/points/42.3000,-83.0000'
    svc = weather.NWSWeatherService(
        time_mod.TimeService('America/Detroit'), 42.30004, -83.00004,
        client=FakeClient({point_url: {'properties': {
            'cwa': 'DTX', 'gridX': 1, 'gridY': 2, 'forecast': 'daily',
            'forecastHourly': 'hourly', 'observationStations': 'stations',
        }}}),
    )
    svc.point = {'forecast_url': None}
    point = await svc.resolve_point()
    assert point['forecast_office'] == 'DTX'
    assert svc.client.urls == [point_url]


@pytest.mark.asyncio
async def test_native_weather_normalizes_point_current_forecast_and_alerts():
    point_url = 'https://api.weather.gov/points/42.3,-83.0'
    responses = {
        point_url: {'properties': {'cwa': 'DTX', 'gridX': 1, 'gridY': 2, 'forecast': 'daily',
                                   'forecastHourly': 'hourly', 'observationStations': 'stations'}},
        'stations': {'observationStations': ['https://api.weather.gov/stations/KDTX']},
        'https://api.weather.gov/stations/KDTX/observations/latest': {'properties': {
            'timestamp': '2026-07-01T11:30:00Z', 'temperature': {'value': 22, 'unitCode': 'wmoUnit:degC'},
            'relativeHumidity': {'value': 60}, 'textDescription': 'Sunny', 'windDirection': {'value': 180},
        }},
        'daily': {'properties': {'periods': [{'name': 'Today', 'startTime': '2026-07-01T06:00:00-04:00',
            'endTime': '2026-07-01T18:00:00-04:00', 'temperature': 78, 'temperatureUnit': 'F',
            'shortForecast': 'Mostly Sunny', 'isDaytime': True}]}},
        'hourly': {'properties': {'periods': [{'startTime': '2026-07-01T12:00:00-04:00',
            'endTime': '2026-07-01T13:00:00-04:00', 'temperature': 78, 'temperatureUnit': 'F',
            'probabilityOfPrecipitation': {'value': 20}, 'shortForecast': 'Sunny'}]}},
        'https://api.weather.gov/alerts/active?point=42.3,-83.0': {'features': [{
            'id': 'urn:oid:1', 'properties': {'event': 'Heat Advisory', 'severity': 'Moderate',
            'sent': '2026-07-01T10:00:00Z', 'expires': '2026-07-01T20:00:00Z', 'areaDesc': ['Wayne']}}]},
    }
    events = []
    svc = service(responses)
    svc.event_sink = lambda code, payload: events.append((code, payload))
    snapshot = await svc.refresh_once()
    assert snapshot['point']['forecast_office'] == 'DTX'
    assert snapshot['current']['temperature'] == 22
    assert snapshot['current']['data_age_seconds'] == 1800
    assert snapshot['hourly'][0]['precipitation_probability'] == 20
    assert snapshot['alerts'][0]['alert_id'] == 'urn:oid:1'
    assert snapshot['health']['status'] == 'healthy'
    assert svc.summary()['active_alert_count'] == 1
    assert events[0][0] == 'weather.alert.new'


@pytest.mark.asyncio
async def test_alert_lifecycle_emits_expired_event():
    svc = service({'https://api.weather.gov/points/42.3,-83.0': {'properties': {}},
                   'https://api.weather.gov/alerts/active?point=42.3,-83.0': {'features': []}})
    events = []
    svc.event_sink = lambda code, payload: events.append(code)
    svc.alerts = {'old': weather.WeatherAlert('old', event='Storm')}
    await svc.refresh_alerts()
    assert events == ['weather.alert.expired']


@pytest.mark.asyncio
async def test_weather_partial_failure_uses_cache_and_degrades():
    responses = {'https://api.weather.gov/points/42.3,-83.0': TimeoutError('offline')}
    svc = service(responses)
    svc.current = weather.WeatherCurrent(temperature=70)
    result = await svc.refresh_once()
    assert result['current']['temperature'] == 70
    assert result['health']['status'] == 'degraded'
    assert result['health']['last_error']


def test_timestamp_rejects_naive_values_and_normalizes_utc():
    assert weather._timestamp('2026-07-01T12:00:00-04:00') == '2026-07-01T16:00:00Z'
    assert weather._timestamp('2026-07-01T12:00:00') is None


@pytest.mark.asyncio
async def test_weather_api_paths_are_read_only(monkeypatch):
    import importlib
    api = importlib.import_module('02_HCM.api')
    class FakeWeather:
        def summary(self): return {'health': 'unavailable', 'active_alert_count': 0}
        def snapshot(self): return {'current': None, 'hourly': [], 'forecast': [], 'alerts': [], 'health': {'status': 'unavailable'}}
    monkeypatch.setattr(api, 'weather_service', FakeWeather())
    user = {'user': 'reader', 'role': 'READONLY'}
    assert (await api.weather_summary(user))['health'] == 'unavailable'
    assert await api.weather_current(user) is None
    assert await api.weather_hourly(user) == []
    assert await api.weather_forecast(user) == []
    assert await api.weather_alerts(user) == []
    assert (await api.weather_health(user))['status'] == 'unavailable'
