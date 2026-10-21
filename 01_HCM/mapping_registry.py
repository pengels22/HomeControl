"""Durable source-to-HCM migration mappings.

Mappings are migration metadata only.  Runtime automation identity remains the
immutable HCM target reference stored in ``target_ref``.
"""
from __future__ import annotations

import json
from uuid import UUID
from . import db

CONFIDENCES = {"EXACT", "SUGGESTED", "AMBIGUOUS", "UNRESOLVED"}
ORIGINS = {"EXACT_AUTOMATIC", "USER_CONFIRMED", "IMPORT_PLANNED", "MIGRATED", "SYSTEM"}
# Confirmation is provenance.  Confidence remains a separate assessment of
# the match and must never be populated with an origin value.
CONFIRMED_ORIGINS = {"EXACT_AUTOMATIC", "USER_CONFIRMED"}
HEALTH = {"VALID", "TARGET_MISSING", "SOURCE_CHANGED", "AMBIGUOUS", "UNCONFIRMED", "INVALID"}


def _uuid(value):
    try: return UUID(str(value))
    except (TypeError, ValueError, AttributeError): raise ValueError("Invalid mapping ID") from None


def _public(row):
    if not row: return None
    result = dict(row)
    return result


async def list_mappings(*, source_system=None, source_kind=None, status=None):
    clauses, args = [], []
    for column, value in (("source_system", source_system), ("source_kind", source_kind), ("status", status)):
        if value is not None: args.append(str(value)); clauses.append(f"{column}=${len(args)}")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    async with db.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM migration_mappings{where} ORDER BY source_system,source_kind,source_identifier", *args)
    return [_public(row) for row in rows]


async def get_mapping(mapping_id):
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM migration_mappings WHERE mapping_id=$1", _uuid(mapping_id))
    if not row: raise LookupError("Mapping not found")
    return _public(row)


async def resolve(source_system, source_kind, source_identifier, *, source_subidentifier=None):
    async with db.acquire() as conn:
        row = await conn.fetchrow("""SELECT * FROM migration_mappings
            WHERE source_system=$1 AND source_kind=$2 AND source_identifier=$3
              AND source_subidentifier IS NOT DISTINCT FROM $4
            UNION ALL
            SELECT m.* FROM migration_mapping_aliases a JOIN migration_mappings m ON m.mapping_id=a.mapping_id
            WHERE a.source_system=$1 AND a.source_kind=$2 AND a.alias_identifier=$3
            LIMIT 1""", source_system, source_kind, source_identifier, source_subidentifier)
    if not row or row["status"] != "VALID" or row["origin"] not in CONFIRMED_ORIGINS: return None
    return _public(row)


async def analyzer_mappings(source_system="home_assistant"):
    rows = await list_mappings(source_system=source_system)
    result = {}
    for row in rows:
        if row["status"] != "VALID" or row["origin"] not in CONFIRMED_ORIGINS: continue
        key = row["source_identifier"]
        value = {"entity_ref": int(row["target_ref"])} if row["target_kind"] in {"entity", "entity_ref", "helper/entity_ref"} and str(row["target_ref"]).isdigit() else row["target_ref"]
        result[key] = value
    aliases = []
    async with db.acquire() as conn:
        aliases = await conn.fetch("""SELECT a.alias_identifier,m.target_kind,m.target_ref,m.status,m.confidence
            FROM migration_mapping_aliases a JOIN migration_mappings m ON m.mapping_id=a.mapping_id
            WHERE m.source_system=$1 AND m.status='VALID' AND m.origin IN ('EXACT_AUTOMATIC','USER_CONFIRMED')""", source_system)
    for row in aliases:
        target = {"entity_ref": int(row["target_ref"])} if row["target_kind"] in {"entity", "entity_ref", "helper/entity_ref"} and str(row["target_ref"]).isdigit() else row["target_ref"]
        result[row["alias_identifier"]] = target
    # Migration 020 remains authoritative for notification/TTS configuration;
    # expose it through the same analyzer input without rewriting that data.
    if source_system == "home_assistant":
        async with db.acquire() as conn:
            for row in await conn.fetch("SELECT source_service,destination_id FROM notification_source_mappings"):
                result[f"notification_destination:{row['source_service']}"] = str(row['destination_id'])
            for row in await conn.fetch("SELECT source_entity,backend_id FROM speech_source_mappings"):
                result[f"speech_backend:{row['source_entity']}"] = str(row['backend_id'])
    return result


async def _target_exists(conn, target_kind, target_ref):
    queries = {
        "entity": "SELECT enabled,available FROM entities WHERE id=$1",
        "entity_ref": "SELECT enabled,available FROM entities WHERE id=$1",
        "helper/entity_ref": "SELECT enabled,available FROM entities WHERE id=$1",
        "device_id": "SELECT enabled,TRUE AS available FROM logical_devices WHERE id=$1",
        "automation_id": "SELECT enabled,TRUE AS available FROM automations WHERE automation_id=$1",
        "script_id": "SELECT enabled,TRUE AS available FROM native_scripts WHERE script_id=$1",
        "scene_id": "SELECT enabled,TRUE AS available FROM native_scenes WHERE scene_id=$1",
        "notification_destination_id": "SELECT enabled,configured AS available FROM notification_destinations WHERE destination_id=$1",
        "speech_backend_id": "SELECT enabled,configured AS available FROM speech_backends WHERE backend_id=$1",
        "room_id": "SELECT enabled,TRUE AS available FROM rooms WHERE id=$1",
        "zone": "SELECT enabled,TRUE AS available FROM zones WHERE zone_id=$1",
    }
    query = queries.get(target_kind)
    if not query: return True, True
    # ``target_ref`` is intentionally TEXT in the mapping schema, while
    # several HCM target tables use integer primary keys.  Coerce only those
    # target kinds so asyncpg receives the type expected by the query.
    integer_targets = {"entity", "entity_ref", "helper/entity_ref", "device_id", "room_id", "zone"}
    query_ref = target_ref
    if target_kind in integer_targets:
        try:
            query_ref = int(str(target_ref))
        except (TypeError, ValueError):
            return False, False
    row = await conn.fetchrow(query, query_ref)
    return (False, False) if not row else (True, bool(row["available"]))


async def validate_mapping(mapping_id):
    mapping = await get_mapping(mapping_id)
    async with db.acquire() as conn:
        exists, available = await _target_exists(conn, mapping["target_kind"], mapping["target_ref"])
        status = "VALID" if exists else "TARGET_MISSING"
        await conn.execute("UPDATE migration_mappings SET status=$2,last_validated_at=now(),updated_at=now() WHERE mapping_id=$1", _uuid(mapping_id), status)
    mapping["status"] = status; mapping["target_available"] = available
    return mapping


async def create_mapping(payload, *, actor=None):
    required = ("source_system", "source_kind", "source_identifier", "target_kind", "target_ref")
    if any(not payload.get(key) for key in required): raise ValueError("Mapping source and target are required")
    confidence = str(payload.get("confidence", "EXACT")).upper()
    origin = str(payload.get("origin", "USER_CONFIRMED")).upper()
    if confidence not in CONFIDENCES: raise ValueError("Invalid mapping confidence")
    if origin not in ORIGINS: raise ValueError("Invalid mapping origin")
    status = "VALID" if origin in CONFIRMED_ORIGINS else "UNCONFIRMED"
    async with db.acquire() as conn:
        existing = await conn.fetchval("""SELECT mapping_id FROM migration_mappings
            WHERE source_system=$1 AND source_kind=$2 AND source_identifier=$3
              AND source_subidentifier IS NOT DISTINCT FROM $4""",
            str(payload["source_system"]),str(payload["source_kind"]),str(payload["source_identifier"]),payload.get("source_subidentifier"))
        if existing: raise ValueError("Authoritative source mapping already exists")
        row = await conn.fetchrow("""INSERT INTO migration_mappings
            (source_system,source_kind,source_identifier,source_subidentifier,source_fingerprint,target_kind,target_ref,status,confidence,origin,notes,actor)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING *""",
            str(payload["source_system"]),str(payload["source_kind"]),str(payload["source_identifier"]),payload.get("source_subidentifier"),payload.get("source_fingerprint"),str(payload["target_kind"]),str(payload["target_ref"]),status,confidence,origin,payload.get("notes"),actor)
    return await validate_mapping(row["mapping_id"])


async def update_mapping(mapping_id, payload, *, actor=None):
    current = await get_mapping(mapping_id)
    values = {**current, **payload}
    confidence = str(values.get("confidence", current["confidence"])).upper()
    if confidence not in CONFIDENCES: raise ValueError("Invalid mapping confidence")
    origin = str(values.get("origin", current["origin"])).upper()
    if origin not in ORIGINS: raise ValueError("Invalid mapping origin")
    status = "VALID" if origin in CONFIRMED_ORIGINS else "UNCONFIRMED"
    async with db.acquire() as conn:
        row = await conn.fetchrow("""UPDATE migration_mappings SET source_fingerprint=$2,target_kind=$3,target_ref=$4,
            confidence=$5,status=$6,origin=$7,notes=$8,actor=$9,updated_at=now() WHERE mapping_id=$1 RETURNING *""",
            _uuid(mapping_id),values.get("source_fingerprint"),values["target_kind"],str(values["target_ref"]),confidence,status,origin,values.get("notes"),actor)
    return await validate_mapping(row["mapping_id"])


async def invalidate_mapping(mapping_id, *, actor=None):
    async with db.acquire() as conn:
        row = await conn.fetchrow("UPDATE migration_mappings SET status='INVALID',actor=$2,updated_at=now() WHERE mapping_id=$1 RETURNING *", _uuid(mapping_id), actor)
    if not row: raise LookupError("Mapping not found")
    return _public(row)


async def add_alias(mapping_id, alias_identifier, *, source_system=None, source_kind=None):
    mapping = await get_mapping(mapping_id)
    async with db.acquire() as conn:
        row = await conn.fetchrow("""INSERT INTO migration_mapping_aliases(mapping_id,source_system,source_kind,alias_identifier)
            VALUES($1,$2,$3,$4) RETURNING *""",_uuid(mapping_id),source_system or mapping["source_system"],source_kind or mapping["source_kind"],str(alias_identifier))
    return _public(row)


async def bulk_create(items, *, actor=None):
    if not isinstance(items, list) or not 1 <= len(items) <= 100: raise ValueError("Bulk mapping size must be 1..100")
    # Each create performs its own short transaction; bounded input prevents
    # unbounded mutation while preserving the same uniqueness checks as single
    # mapping creation.
    return [await create_mapping(item, actor=actor) for item in items]
