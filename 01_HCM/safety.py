from __future__ import annotations
import logging
from . import db
from .devices import command_logical
from .notifications import notifications, Notification

log = logging.getLogger(__name__)

class SafetyController:
    def __init__(self, hvac):
        self.hvac = hvac
        self.fire_active = False

    async def set_fire(self, active: bool):
        if active == self.fire_active:
            return
        self.fire_active = active
        async with db.acquire() as conn:
            await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'fire', active, '{}')
        if active:
            await self.hvac.force_off()
            await notifications.send(Notification(title='Fire alarm', body='Fire alarm active. HVAC shut down and available lights commanded on.', priority='critical', category='life_safety'))
            # Life-safety light sweep is database-driven and skips maintenance-locked devices.
            async with db.acquire() as conn:
                rows = await conn.fetch("SELECT logical_name FROM logical_devices WHERE device_class='light' AND enabled=true AND maintenance_locked=false")
            for r in rows:
                try:
                    await command_logical(r['logical_name'], {'op':'light','percent':100,'value':True})
                except Exception:
                    log.exception('failed life-safety light command: %s', r['logical_name'])
