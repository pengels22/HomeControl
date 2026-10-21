"""Persistent, sanitized and non-executable HA migration workspace."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from . import db


def resolve_source_state(source: dict, runtime_state: dict[str, bool] | None = None) -> tuple[bool, str]:
    runtime_state = runtime_state or {}
    name = str(source.get("alias") or source.get("name") or source.get("id") or "")
    if runtime_state:
        return bool(runtime_state.get(name, True)), "HA_RUNTIME_STATE"
    if isinstance(source.get("initial_state"), bool):
        return bool(source["initial_state"]), "HA_INITIAL_STATE"
    return True, "IMPORT_DEFAULT_ENABLED"


def _row(row):
    if not row: return None
    value = dict(row)
    for key in ("staged_id", "created_at", "updated_at"):
        if key in value and isinstance(value[key], UUID): value[key] = str(value[key])
    return value


async def list_items(*, search=None, source_kind=None, compatibility=None, source_enabled=None, limit=200, offset=0):
    clauses = ["source_system='home_assistant'"]
    args = []
    if search:
        args.append(f"%{str(search)[:120]}%"); clauses.append(f"source_name ILIKE ${len(args)}")
    if source_kind:
        args.append(str(source_kind)); clauses.append(f"source_kind=${len(args)}")
    if compatibility:
        args.append(str(compatibility)); clauses.append(f"compatibility_status=${len(args)}")
    if source_enabled is not None:
        args.append(bool(source_enabled)); clauses.append(f"source_enabled=${len(args)}")
    where = " AND ".join(clauses)
    async with db.acquire() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM ha_migration_items WHERE {where}", *args)
        args.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = await conn.fetch(f"SELECT * FROM ha_migration_items WHERE {where} ORDER BY source_name,source_identifier LIMIT ${len(args)-1} OFFSET ${len(args)}", *args)
    return {"items": [_row(row) for row in rows], "total": int(total or 0), "limit": args[-2], "offset": args[-1]}


async def get_item(staged_id):
    async with db.acquire() as conn: row = await conn.fetchrow("SELECT * FROM ha_migration_items WHERE staged_id=$1", UUID(str(staged_id)))
    if not row: raise LookupError("Staged migration item not found")
    return _row(row)


async def ingest_plan(plan: dict[str, Any], *, runtime_state: dict[str, bool] | None = None, state_provenance="HA_RUNTIME_STATE"):
    """Upsert analyzer output; staged records never become executable objects."""
    runtime_state = {str(k): bool(v) for k, v in (runtime_state or {}).items()}
    if state_provenance not in {"HA_RUNTIME_STATE", "HA_INITIAL_STATE", "IMPORT_DEFAULT_ENABLED"}:
        raise ValueError("Invalid state provenance")
    records = []
    async with db.acquire() as conn:
        for item in plan.get("items", []):
            if item.get("source_type") != "automations": continue
            source = item.get("source") or {}
            name = str(item.get("source_name") or item.get("source_id") or "Unnamed automation")[:512]
            enabled, provenance = resolve_source_state(source, runtime_state)
            preview = dict(item.get("preview") or {})
            preview["enabled"] = enabled
            summary = {"compatibility": item.get("compatibility"), "eligibility": item.get("eligibility"),
                       "required_mappings": item.get("required_mappings", []), "referenced_services": item.get("referenced_services", []),
                       "planned_helpers": item.get("planned_native_helpers", []), "warnings": item.get("warnings", []), "errors": item.get("errors", [])}
            row = await conn.fetchrow("""INSERT INTO ha_migration_items
                (source_kind,source_identifier,source_name,source_document,source_fingerprint,source_enabled,state_provenance,compatibility_status,compatibility_summary,native_preview)
                VALUES('automation',$1,$2,$3::jsonb,$4,$5,$6,$7,$8::jsonb,$9::jsonb)
                ON CONFLICT(source_system,source_kind,source_identifier) DO UPDATE SET
                  source_name=EXCLUDED.source_name,source_document=EXCLUDED.source_document,source_fingerprint=EXCLUDED.source_fingerprint,
                  source_enabled=EXCLUDED.source_enabled,state_provenance=EXCLUDED.state_provenance,compatibility_status=EXCLUDED.compatibility_status,
                  compatibility_summary=EXCLUDED.compatibility_summary,native_preview=EXCLUDED.native_preview,
                  source_revision=ha_migration_items.source_revision+1,updated_at=now()
                RETURNING *""", str(item.get("source_id")), name, json.dumps(source), item.get("source_fingerprint") or "", enabled, provenance,
                item.get("eligibility", "BLOCKED_UNSUPPORTED"), json.dumps(summary), json.dumps(preview))
            records.append(_row(row))
    return {"items": records, "count": len(records), "source_system": "home_assistant", "runtime_executable": False}


async def update_source_enabled(staged_id, enabled: bool):
    async with db.acquire() as conn:
        row = await conn.fetchrow("UPDATE ha_migration_items SET source_enabled=$2,state_provenance='HA_RUNTIME_STATE',native_preview=jsonb_set(native_preview,'{enabled}',$3::jsonb),updated_at=now() WHERE staged_id=$1 RETURNING *", UUID(str(staged_id)), bool(enabled), json.dumps(bool(enabled)))
    if not row: raise LookupError("Staged migration item not found")
    return _row(row)
