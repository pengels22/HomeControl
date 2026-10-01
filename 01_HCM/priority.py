from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from . import db


class OutputSource(str, Enum):
    LIFE_SAFETY = "life_safety"
    LOCAL_OVERRIDE = "local_override"
    USER = "user"
    RULES = "rules"


SOURCE_RANK: dict[OutputSource, int] = {
    OutputSource.LIFE_SAFETY: 300,
    OutputSource.LOCAL_OVERRIDE: 200,
    OutputSource.USER: 100,
    OutputSource.RULES: 100,
}


@dataclass(slots=True)
class OutputIntent:
    logical_device_id: int
    source: OutputSource
    command: dict[str, Any]
    rank: int


def coerce_source(source: str | OutputSource) -> OutputSource:
    if isinstance(source, OutputSource):
        return source
    return OutputSource(str(source))


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


async def record_intent(logical_device_id: int, source: str | OutputSource, command: dict[str, Any]) -> None:
    src = coerce_source(source)
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO output_intents(logical_device_id,source,command,active,updated_at)
            VALUES($1,$2,$3::jsonb,true,now())
            ON CONFLICT(logical_device_id,source)
            DO UPDATE SET command=EXCLUDED.command, active=true, updated_at=now(), expires_at=NULL
            """,
            logical_device_id,
            src.value,
            _json(command),
        )


async def clear_intent(logical_device_id: int, source: str | OutputSource) -> None:
    src = coerce_source(source)
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE output_intents SET active=false, updated_at=now() WHERE logical_device_id=$1 AND source=$2",
            logical_device_id,
            src.value,
        )


async def clear_source(source: str | OutputSource) -> list[int]:
    src = coerce_source(source)
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE output_intents SET active=false, updated_at=now()
            WHERE source=$1 AND active=true
            RETURNING logical_device_id
            """,
            src.value,
        )
    return [int(r["logical_device_id"]) for r in rows]


async def active_intent(logical_device_id: int) -> OutputIntent | None:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT logical_device_id, source, command
            FROM output_intents
            WHERE logical_device_id=$1
              AND active=true
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY updated_at DESC
            """,
            logical_device_id,
        )
    intents: list[OutputIntent] = []
    for row in rows:
        src = coerce_source(row["source"])
        command = row["command"] or {}
        if isinstance(command, str):
            command = json.loads(command)
        intents.append(OutputIntent(logical_device_id, src, dict(command), SOURCE_RANK[src]))
    return max(intents, key=lambda i: i.rank, default=None)


async def logical_names_for_ids(logical_device_ids: Iterable[int]) -> dict[int, str]:
    ids = list({int(i) for i in logical_device_ids})
    if not ids:
        return {}
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT id, logical_name FROM logical_devices WHERE id=ANY($1::bigint[])", ids)
    return {int(r["id"]): r["logical_name"] for r in rows}
