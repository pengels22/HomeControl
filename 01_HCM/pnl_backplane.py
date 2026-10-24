"""PNL backplane validation and panel-scoped local entity aliases."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

LOCAL_FIELDS = {
    'local.lux': ('illuminance', 'lux'),
    'local.occupancy': ('occupancy', None),
    'local.temp': ('temperature', 'C'),
    'local.humidity': ('humidity', '%'),
}
STALE_AFTER_SECONDS = 15


class PNLTelemetryError(ValueError):
    pass


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode('utf-8')).hexdigest()


def verify_token(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), str(expected_hash))


def validate_telemetry(payload: dict[str, Any], *, device_id: str,
                       last_sequence: int, now: float | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PNLTelemetryError('telemetry must be an object')
    if payload.get('device_id') != device_id:
        raise PNLTelemetryError('telemetry identity mismatch')
    sequence = payload.get('sequence')
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise PNLTelemetryError('sequence must be a non-negative integer')
    if sequence <= int(last_sequence):
        raise PNLTelemetryError('stale or replayed telemetry sequence')
    timestamp = payload.get('timestamp')
    if not isinstance(timestamp, str):
        raise PNLTelemetryError('timestamp is required')
    try:
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError as exc:
        raise PNLTelemetryError('timestamp must be ISO-8601') from exc
    if parsed.tzinfo is None:
        raise PNLTelemetryError('timestamp must include a timezone')
    age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() if now is None else now - parsed.timestamp()
    if age < -30 or age > 60:
        raise PNLTelemetryError('telemetry timestamp outside acceptance window')
    values = payload.get('local')
    if not isinstance(values, dict) or set(values) != {'lux', 'occupancy', 'temp', 'humidity'}:
        raise PNLTelemetryError('local telemetry must contain lux, occupancy, temp, humidity')
    if values['occupancy'] is not None and not isinstance(values['occupancy'], bool):
        raise PNLTelemetryError('local.occupancy must be boolean or null')
    for key in ('lux', 'temp', 'humidity'):
        value = values[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise PNLTelemetryError(f'local.{key} must be numeric or null')
    validity = payload.get('validity', {key: values[key] is not None for key in ('lux', 'occupancy', 'temp', 'humidity')})
    if not isinstance(validity, dict) or set(validity) != {'lux', 'occupancy', 'temp', 'humidity'} or any(not isinstance(value, bool) for value in validity.values()):
        raise PNLTelemetryError('sensor validity must contain boolean values for every local sensor')
    if values['lux'] is not None and not 0 <= float(values['lux']) <= 200000:
        raise PNLTelemetryError('local.lux outside supported range')
    if values['humidity'] is not None and not 0 <= float(values['humidity']) <= 100:
        raise PNLTelemetryError('local.humidity outside supported range')
    if values['temp'] is not None and not -50 <= float(values['temp']) <= 80:
        raise PNLTelemetryError('local.temp outside supported range')
    return {'device_id': device_id, 'sequence': sequence,
            'timestamp': parsed.astimezone(timezone.utc).isoformat(), 'local': values, 'validity': validity}


def telemetry_is_stale(last_telemetry_at: float | None, now: float, threshold: float = STALE_AFTER_SECONDS) -> bool:
    """Return freshness independently of the Unified Heartbeat V3 channel."""
    return last_telemetry_at is None or now - last_telemetry_at > threshold


def local_aliases(device_id: str, local: dict[str, Any], validity: dict[str, bool] | None = None) -> list[dict[str, Any]]:
    validity = validity or {key: local.get(key) is not None for key in ('lux', 'occupancy', 'temp', 'humidity')}
    return [
        {'entity_id': f'pnl_{device_id}_{key.replace(".", "_")}', 'alias': key,
         'panel_id': device_id, 'capability': capability, 'unit': unit,
         'state': local.get(key.split('.', 1)[1]), 'valid': bool(validity.get(key.split('.', 1)[1], False))}
        for key, (capability, unit) in LOCAL_FIELDS.items()
    ]
