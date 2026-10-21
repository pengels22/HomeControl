"""Persistent, sanitized and non-executable HA migration workspace."""
from __future__ import annotations

import json
import hashlib
from collections import Counter, defaultdict
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


def normalized_alias(value: Any) -> str:
    return str(value or "").strip()


def stable_source_identifier(item: dict[str, Any]) -> str:
    """Return an identity independent of the human-readable alias."""
    source = item.get("source") or {}
    explicit = source.get("id")
    if explicit is not None and str(explicit).strip():
        return str(explicit)
    fingerprint = str(item.get("source_fingerprint") or "")
    if not fingerprint:
        fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return f"fingerprint:{fingerprint}"


def audit_source_items(plan: dict[str, Any], runtime_state: dict[str, bool] | None = None) -> dict[str, Any]:
    """Audit identity and resolve a human-readable runtime snapshot safely."""
    items = [x for x in plan.get("items", []) if x.get("source_type") == "automations"]
    identifiers = [stable_source_identifier(x) for x in items]
    aliases = [str(x.get("source_name") or (x.get("source") or {}).get("alias") or "") for x in items]
    alias_map: dict[str, list[int]] = defaultdict(list)
    for index, alias in enumerate(aliases):
        alias_map[normalized_alias(alias)].append(index)
    state = {str(k): bool(v) for k, v in (runtime_state or {}).items()}
    errors = []
    assignments = {}
    for requested, enabled in state.items():
        candidates = alias_map.get(normalized_alias(requested), [])
        if len(candidates) != 1:
            errors.append({"alias": requested, "match_count": len(candidates), "reason": "missing_or_ambiguous"})
        else:
            assignments[identifiers[candidates[0]]] = enabled
    duplicate_aliases = {alias: [identifiers[i] for i in indexes] for alias, indexes in alias_map.items() if len(indexes) > 1}
    exact_records = Counter(json.dumps((x.get("source") or {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False) for x in items)
    explicit = [((x.get("source") or {}).get("id")) for x in items]
    explicit = [str(x) for x in explicit if x is not None and str(x).strip()]
    return {"ok": not errors and len(set(identifiers)) == len(identifiers), "items": items, "identities": identifiers,
            "state_assignments": assignments, "errors": errors, "explicit_id_count": len(explicit),
            "fallback_id_count": len(items) - len(explicit), "duplicate_ids": [k for k, v in Counter(identifiers).items() if v > 1],
            "duplicate_aliases": duplicate_aliases, "whitespace_aliases": [a for a in aliases if a != a.strip()],
            "case_only_aliases": [], "exact_duplicate_records": [k for k, v in exact_records.items() if v > 1]}


def _row(row):
    if not row: return None
    value = dict(row)
    for key in ("staged_id", "created_at", "updated_at"):
        if key in value and isinstance(value[key], UUID): value[key] = str(value[key])
    value["display_name"] = normalized_alias(value.get("source_name"))
    value["source_identifier_suffix"] = hashlib.sha256(str(value.get("source_identifier", "")).encode()).hexdigest()[-8:]
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
    if state_provenance not in {"HA_RUNTIME_STATE", "HA_INITIAL_STATE", "IMPORT_DEFAULT_ENABLED"}:
        raise ValueError("Invalid state provenance")
    audit = audit_source_items(plan, runtime_state)
    if not audit["ok"]:
        safe_audit = {k: v for k, v in audit.items() if k not in {"items", "identities", "exact_duplicate_records"}}
        raise ValueError(json.dumps({"message": "HA source identity/state audit failed", "audit": safe_audit}, sort_keys=True))
    records = []
    async with db.acquire() as conn:
        for item in plan.get("items", []):
            if item.get("source_type") != "automations": continue
            source = item.get("source") or {}
            name = str(item.get("source_name") or item.get("source_id") or "Unnamed automation")[:512]
            identifier = stable_source_identifier(item)
            enabled = audit["state_assignments"].get(identifier, True)
            provenance = state_provenance if runtime_state else resolve_source_state(source)[1]
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
                RETURNING *""", identifier, name, json.dumps(source), item.get("source_fingerprint") or "", enabled, provenance,
                item.get("eligibility", "BLOCKED_UNSUPPORTED"), json.dumps(summary), json.dumps(preview))
            records.append(_row(row))
    return {"items": records, "count": len(records), "source_system": "home_assistant", "runtime_executable": False}


async def update_source_enabled(staged_id, enabled: bool):
    async with db.acquire() as conn:
        row = await conn.fetchrow("UPDATE ha_migration_items SET source_enabled=$2,state_provenance='HA_RUNTIME_STATE',native_preview=jsonb_set(native_preview,'{enabled}',$3::jsonb),updated_at=now() WHERE staged_id=$1 RETURNING *", UUID(str(staged_id)), bool(enabled), json.dumps(bool(enabled)))
    if not row: raise LookupError("Staged migration item not found")
    return _row(row)
