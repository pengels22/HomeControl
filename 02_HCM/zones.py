"""Native, provider-neutral zone membership and transition semantics."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from . import db

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_HYSTERESIS_M = 5.0


def distance_m(latitude_a, longitude_a, latitude_b, longitude_b):
    """Return great-circle distance in metres using the haversine formula."""
    lat1, lat2 = math.radians(float(latitude_a)), math.radians(float(latitude_b))
    dlat = lat2 - lat1
    dlon = math.radians(float(longitude_b) - float(longitude_a))
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


class ZoneEvaluator:
    """Evaluate tracker updates without polling or external location services."""

    def __init__(self, zones=None, *, hysteresis_m=DEFAULT_HYSTERESIS_M, event_sink=None):
        self.zones = {str(z['zone_id']): dict(z) for z in (zones or [])}
        self.membership = {}
        self.hysteresis_m = max(0.0, float(hysteresis_m))
        self.event_sink = event_sink

    def set_zones(self, zones):
        self.zones = {str(z['zone_id']): dict(z) for z in zones}

    def disable(self, zone_ref):
        self.membership = {(tracker, zone): value for (tracker, zone), value in self.membership.items() if zone != str(zone_ref)}
        if str(zone_ref) in self.zones:
            self.zones[str(zone_ref)]['enabled'] = False

    def is_member(self, tracker_ref, zone_ref):
        return self.membership.get((str(tracker_ref), str(zone_ref)))

    async def update(self, tracker_ref, latitude=None, longitude=None, *, accuracy=None,
                     available=True, timestamp=None, context=None):
        tracker_ref = str(tracker_ref)
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        if not available or latitude is None or longitude is None:
            return []
        events = []
        accuracy_m = max(0.0, float(accuracy or 0.0))
        for zone_ref, zone in self.zones.items():
            if not zone.get('enabled', True):
                continue
            distance = distance_m(latitude, longitude, zone['latitude'], zone['longitude'])
            old = self.membership.get((tracker_ref, zone_ref))
            if old is None:
                self.membership[(tracker_ref, zone_ref)] = distance + accuracy_m <= zone['radius_m']
                continue
            if old:
                current = distance - accuracy_m <= zone['radius_m'] + self.hysteresis_m
            else:
                current = distance + accuracy_m <= zone['radius_m']
            if current == old:
                continue
            self.membership[(tracker_ref, zone_ref)] = current
            event_name = 'enter' if current else 'leave'
            event = {'event': event_name, 'tracker_ref': tracker_ref, 'zone_ref': zone_ref,
                     'timestamp': timestamp, 'previous_membership': old,
                     'current_membership': current, 'source_context': context or {}}
            events.append(event)
            if self.event_sink is not None:
                result = self.event_sink(event)
                if hasattr(result, '__await__'):
                    await result
        return events


class ZoneStore:
    async def list(self, *, enabled=None):
        clause = '' if enabled is None else ' WHERE enabled=$1'
        args = [] if enabled is None else [bool(enabled)]
        async with db.acquire() as conn:
            rows = await conn.fetch(f'SELECT * FROM zones{clause} ORDER BY name,zone_id', *args)
        return [dict(row) for row in rows]

    async def get(self, zone_id):
        async with db.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM zones WHERE zone_id=$1', zone_id)
        if not row:
            raise LookupError('Zone not found')
        return dict(row)

    async def create(self, body):
        self._validate(body)
        async with db.acquire() as conn:
            row = await conn.fetchrow('''INSERT INTO zones(name,enabled,latitude,longitude,radius_m,icon,metadata)
                VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING *''', body['name'], body.get('enabled', True),
                body['latitude'], body['longitude'], body['radius_m'], body.get('icon'), __import__('json').dumps(body.get('metadata', {})))
        return dict(row)

    async def update(self, zone_id, body):
        self._validate(body, partial=True)
        fields = {key: body[key] for key in ('name', 'enabled', 'latitude', 'longitude', 'radius_m', 'icon') if key in body}
        if 'metadata' in body: fields['metadata'] = __import__('json').dumps(body['metadata'])
        if not fields: return await self.get(zone_id)
        fields['updated_at'] = datetime.now(timezone.utc)
        assignments = ','.join(f'{key}=${i + 2}' for i, key in enumerate(fields))
        async with db.acquire() as conn:
            row = await conn.fetchrow(f'UPDATE zones SET {assignments} WHERE zone_id=$1 RETURNING *', zone_id, *fields.values())
        if not row: raise LookupError('Zone not found')
        return dict(row)

    async def delete(self, zone_id):
        async with db.acquire() as conn:
            refs = await conn.fetch("""SELECT automation_id FROM automations
                WHERE trigger_definitions::text LIKE '%' || $1 || '%' OR condition_definition::text LIKE '%' || $1 || '%'""", str(zone_id))
            if refs:
                raise ValueError({'message': 'Zone is referenced by automations', 'automation_ids': [str(r['automation_id']) for r in refs]})
            result = await conn.execute('DELETE FROM zones WHERE zone_id=$1', zone_id)
        return result.endswith('1')

    @staticmethod
    def _validate(body, partial=False):
        required = ('name', 'latitude', 'longitude', 'radius_m')
        if not partial and any(key not in body for key in required):
            raise ValueError('name, latitude, longitude and radius_m are required')
        if 'name' in body and (not isinstance(body['name'], str) or not body['name'].strip()): raise ValueError('Invalid zone name')
        if 'latitude' in body and not -90 <= float(body['latitude']) <= 90: raise ValueError('Invalid latitude')
        if 'longitude' in body and not -180 <= float(body['longitude']) <= 180: raise ValueError('Invalid longitude')
        if 'radius_m' in body and not 0 < float(body['radius_m']) <= 100000: raise ValueError('Invalid radius_m')


class ZoneRuntime:
    """Loads configured zones and publishes normalized events through HCM's bus."""

    def __init__(self, registry):
        self.registry = registry
        self.store = ZoneStore()
        self.evaluator = ZoneEvaluator(event_sink=self._publish)

    async def start(self):
        await self.reload()

    async def reload(self):
        self.evaluator.set_zones(await self.store.list())

    async def ingest_tracker(self, tracker_ref, latitude, longitude, **kwargs):
        return await self.evaluator.update(tracker_ref, latitude, longitude, **kwargs)

    async def _publish(self, event):
        await self.registry.context('hcm_native').emit(
            f"hcm_native.zone.{event['event']}", event)
