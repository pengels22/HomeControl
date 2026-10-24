"""Bounded, provider-neutral normalized command events."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from . import db

MAX_TEXT = 256
MAX_PHRASES = 16
MAX_PHRASE = 128
_SPACE = re.compile(r"\s+")


def normalize_command(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Command text must be a string")
    value = _SPACE.sub(" ", text.strip()).casefold()
    if not value or len(value) > MAX_TEXT:
        raise ValueError("Command text must be 1..256 characters")
    return value


def normalize_phrases(phrases):
    if isinstance(phrases, str):
        phrases = [phrases]
    if not isinstance(phrases, list) or not 1 <= len(phrases) <= MAX_PHRASES:
        raise ValueError("Conversation trigger needs 1..16 phrases")
    result = []
    for phrase in phrases:
        normalized = normalize_command(phrase)
        if len(normalized) > MAX_PHRASE:
            raise ValueError("Conversation phrases are limited to 128 characters")
        if normalized not in result:
            result.append(normalized)
    return result


async def ingest(registry, text: str, *, source="authenticated_command", source_event_id=None,
                 user=None, language=None):
    normalized = normalize_command(text)
    source_event_id = str(source_event_id)[:128] if source_event_id else None
    if source_event_id:
        async with db.acquire() as conn:
            duplicate = await conn.fetchval("""SELECT event_id FROM integration_events
                WHERE event_type='hcm_native.command' AND payload->>'source_event_id'=$1
                ORDER BY event_id DESC LIMIT 1""", source_event_id)
        if duplicate is not None:
            return {"accepted": True, "duplicate": True, "event_id": None, "normalized_text": normalized}
    payload = {"normalized_text": normalized, "source": str(source)[:64],
               "timestamp": datetime.now(timezone.utc).isoformat(), "event_id": str(uuid4())}
    if source_event_id:
        payload["source_event_id"] = source_event_id
    if user:
        payload["user"] = str(user)[:64]
    if language:
        payload["language"] = str(language)[:32]
    event = await registry.context("hcm_native").emit("hcm_native.command", payload,
                                                        correlation_id=source_event_id)
    return {"accepted": True, "duplicate": False, "event_id": getattr(event, "event_id", None),
            "normalized_text": normalized}
