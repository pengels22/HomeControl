from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from . import db

Priority = Literal['normal', 'critical']

@dataclass(slots=True)
class Notification:
    title: str
    body: str
    priority: Priority = 'normal'
    category: str = 'general'
    data: dict[str, Any] | None = None

class NotificationService:
    """First-pass notification abstraction.

    Events are persisted now; APNs/Watch delivery is intentionally a provider adapter
    to be added when Apple signing, bundle IDs, and production credentials exist.
    """
    async def send(self, n: Notification) -> None:
        async with db.acquire() as conn:
            await conn.execute(
                "INSERT INTO notification_log(title,body,priority,category,data) VALUES($1,$2,$3,$4,$5::jsonb)",
                n.title, n.body, n.priority, n.category, json.dumps(n.data or {})
            )

notifications = NotificationService()
