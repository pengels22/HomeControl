"""Provider-neutral normalized device-event contract and durable emission."""
from __future__ import annotations

from datetime import datetime, timezone

MAX_STRING = 128
MAX_METADATA_KEYS = 16
MAX_METADATA_DEPTH = 3


def _bounded(value, depth=0):
    if depth > MAX_METADATA_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k)[:MAX_STRING]: _bounded(v, depth + 1) for k, v in list(value.items())[:MAX_METADATA_KEYS]}
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value[:MAX_METADATA_KEYS]]
    return str(value)[:MAX_STRING]


def normalize_device_event(*, device_ref, category, action, entity_ref=None,
                           subtype=None, value=None, sequence=None, timestamp=None,
                           provider_id=None, source_event_id=None, metadata=None):
    if not device_ref or not category or not action:
        raise ValueError('device_ref, category and action are required')
    event = {'device_ref': str(device_ref)[:MAX_STRING], 'category': str(category)[:MAX_STRING],
             'action': str(action)[:MAX_STRING], 'timestamp': timestamp or datetime.now(timezone.utc).isoformat()}
    for key, item in (('entity_ref', entity_ref), ('subtype', subtype), ('value', value),
                      ('sequence', sequence), ('provider_id', provider_id), ('source_event_id', source_event_id)):
        if item is not None: event[key] = _bounded(item)
    if metadata: event['metadata'] = _bounded(metadata)
    return event


class DeviceEventRuntime:
    """Normalize provider events and send them through the existing event log."""
    def __init__(self, registry):
        self.registry = registry
        self._seen = {}

    async def emit(self, event, *, provider_id='provider', source_event_id=None):
        source_event_id = source_event_id or event.get('source_event_id')
        if source_event_id is not None:
            key = (str(provider_id), str(source_event_id))
            if key in self._seen: return None
            self._seen[key] = event.get('timestamp')
            if len(self._seen) > 2048: self._seen.pop(next(iter(self._seen)))
        payload = dict(event); payload['provider_id'] = str(provider_id)
        if source_event_id is not None: payload['source_event_id'] = str(source_event_id)[:MAX_STRING]
        return await self.registry.context('hcm_native').emit('hcm_native.device_event', payload)
