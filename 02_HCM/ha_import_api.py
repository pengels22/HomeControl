"""Authenticated Home Assistant migration endpoints.

Analysis accepts data supplied by the caller only.  It never reads a path or a
live HA instance.  Apply requires an ADMIN and an explicit plan plus selection;
the plan is revalidated before native stores are called.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from copy import deepcopy

from .auth import require_user
from .ha_importer import (
    BLOCKED_MAPPING, BLOCKED_SERVICE, BLOCKED_UNSUPPORTED, HAImportError,
    analyze_home_assistant, analyze_yaml, parse_registry_exports,
)
from .integrations.runtime import runtime as integrations
from . import mapping_registry
from .ha_capability_enrichment import enrich_plan
from .ha_mapping_review import build_mapping_queue, preview_mapping
from .hcm_target_catalog import candidates as catalog_candidates, catalog_from_rows, load_catalog, summary as catalog_summary
from . import db

router = APIRouter(prefix="/api/v1/import/home-assistant", dependencies=[Depends(require_user)])

# Helpers are native HCM entities.  ``entity_ref`` is the canonical mapping
# target kind; slash-qualified kinds are rejected by the mapping schema.
IMPORT_HELPER_TARGET_KIND = "entity_ref"


def _admin(user: dict[str, str]):
    if user.get("role") != "ADMIN":
        raise HTTPException(403, "ADMIN role required")


async def _analysis_mappings(temporary):
    try:
        durable = await mapping_registry.analyzer_mappings("home_assistant")
    except Exception:
        durable = {}
    return {**durable, **(temporary or {})}


async def _request_plan(body: dict, mappings: dict | None = None):
    registry = parse_registry_exports(body.get("ha_entity_registry"), body.get("ha_device_registry"), body.get("ha_area_registry")) if any(key in body for key in ("ha_entity_registry", "ha_device_registry", "ha_area_registry")) else None
    effective = await _analysis_mappings(mappings or body.get("mappings") or {})
    if any(k in body for k in ("automations_yaml", "scripts_yaml", "scenes_yaml")):
        plan = analyze_yaml(automations=body.get("automations_yaml"), scripts=body.get("scripts_yaml"), scenes=body.get("scenes_yaml"), mappings=effective, registry=registry)
    else:
        plan = analyze_home_assistant(body.get("sources", body.get("source", body)), mappings=effective, registry=registry)
    if getattr(integrations, "registry", None) is not None:
        try: plan = await enrich_plan(plan, integrations.registry.services)
        except Exception: pass
    try:
        async with db.acquire() as conn:
            helper_rows = await conn.fetch("SELECT entity_ref,entity_id,helper_type,config FROM native_helpers")
        plan = _resolve_native_helper_plans(plan, helper_rows)
    except Exception:
        # Analysis remains usable when the optional native inventory is
        # unavailable; apply still performs authoritative collision checks.
        pass
    return plan


def _resolve_native_helper_plans(plan, helper_rows):
    """Annotate deterministic helper reuse without creating mappings.

    Native helper identity is the immutable entity reference selected by the
    stable entity_id and helper_type pair.  The importer-owned mapping may be
    absent before the first apply, so preview must consult native inventory
    separately from confirmed external mappings.
    """
    result = deepcopy(plan)
    by_identity = {(str(row.get("entity_id")), str(row.get("helper_type"))): row
                   for row in helper_rows or []}
    for item in result.get("items", []):
        planned = item.get("planned_native_helpers") or []
        resolved = []
        for helper in planned:
            identity = str(helper.get("proposed_entity_id") or helper.get("source_identity") or "")
            row = by_identity.get((identity, str(helper.get("helper_type"))))
            if row:
                resolved.append({**helper, "decision": "REUSE",
                                 "target_entity_ref": int(row["entity_ref"]),
                                 "definition_available": False,
                                 "reuse_evidence": "entity_id_and_helper_type"})
            else:
                resolved.append(helper)
        if not resolved:
            continue
        item["planned_native_helpers"] = resolved
        preview = item.get("preview") or {}
        preview["native_objects_to_reuse"] = [h for h in resolved if h.get("decision") == "REUSE"]
        preview["native_objects_to_create"] = [h for h in resolved if h.get("decision") == "CREATE"]
        item["preview"] = preview
    return result


async def _mapping_candidates(target_catalog=None):
    if target_catalog is not None:
        return catalog_candidates(load_catalog(target_catalog))
    try:
        rows = await integrations.registry.inspect("entities")
        devices = await integrations.registry.inspect("devices")
        destinations, backends, zones = [], [], []
        try:
            from . import notification_config
            destinations = await notification_config.list_destinations()
            backends = await notification_config.list_backends()
        except Exception: pass
        try:
            from .zones import ZoneStore
            zones = await ZoneStore().list()
        except Exception: pass
        catalog = catalog_from_rows(entities=rows, devices=devices, zones=zones,
            notification_destinations=destinations, speech_backends=backends, source_mode="runtime")
        return catalog_candidates(catalog)
    except Exception:
        return []


@router.get("/target-catalog")
async def target_catalog(user=Depends(require_user)):
    """Read-only, purpose-built HCM target metadata; never calls providers."""
    _admin(user)
    try:
        candidates = await _mapping_candidates()
        catalog = catalog_from_rows(
            entities=[row for row in candidates if row.get("target_kind") == "entity"],
            devices=[row for row in candidates if row.get("target_kind") == "device"],
            zones=[row for row in candidates if row.get("target_kind") == "zone"],
            notification_destinations=[row for row in candidates if row.get("target_kind") == "notification_destination"],
            speech_backends=[row for row in candidates if row.get("target_kind") == "speech_backend"], source_mode="runtime")
        return catalog_summary(catalog)
    except Exception:
        return catalog_summary(catalog_from_rows(source_mode="unavailable", provenance={"reason": "runtime database unavailable"}))


@router.post("/analyze")
async def analyze(body: dict, user=Depends(require_user)):
    _admin(user)
    try:
        return await _request_plan(body)
    except HAImportError as exc:
        raise HTTPException(400, str(exc)) from None
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/mapping-queue")
async def mapping_queue(body: dict | None = None, source_kind: str | None = None,
                        domain: str | None = None, search: str | None = None,
                        status: str | None = None, user=Depends(require_user)):
    """Return a bounded sanitized queue; source data is supplied by the caller."""
    _admin(user)
    body = body or {}
    try:
        plan = await _request_plan(body)
        records = await mapping_registry.list_mappings(source_system="home_assistant")
        queue = build_mapping_queue(plan, durable_records=records, candidates=await _mapping_candidates(body.get("target_catalog")), limit=body.get("limit", 500))
        if source_kind or domain or search or status:
            queue["items"] = [item for item in queue["items"] if
                (not source_kind or item["source_kind"] == source_kind) and
                (not domain or item.get("domain") == domain) and
                (not status or item.get("mapping_health") == status) and
                (not search or search.casefold() in (item["source_identifier"] + " " + item["display_name"]).casefold())]
            queue["total"] = len(queue["items"])
        return queue
    except (HAImportError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/mapping-queue")
async def mapping_queue_post(body: dict, user=Depends(require_user)):
    return await mapping_queue(body=body, user=user)


@router.post("/mapping-preview")
async def mapping_preview(body: dict, user=Depends(require_user)):
    _admin(user)
    source_identifier = body.get("source_identifier")
    if not source_identifier or "target" not in body: raise HTTPException(400, "source_identifier and target are required")
    try:
        base_mappings = await _analysis_mappings(body.get("mappings") or {})
        plan = await _request_plan(body, base_mappings)
        if body.get("analysis_revision") and body["analysis_revision"] != build_mapping_queue(plan)["analysis_revision"]:
            raise HTTPException(409, "Analysis revision is stale; re-run analysis before preview")
        def rerun(temporary):
            # This closure is intentionally synchronous for the pure preview helper.
            registry = parse_registry_exports(body.get("ha_entity_registry"), body.get("ha_device_registry"), body.get("ha_area_registry")) if any(key in body for key in ("ha_entity_registry", "ha_device_registry", "ha_area_registry")) else None
            sources = body.get("sources", body.get("source", body))
            return analyze_home_assistant(sources, mappings={**base_mappings, source_identifier: temporary[source_identifier]}, registry=registry)
        return preview_mapping(plan, str(source_identifier), body["target"], mappings=base_mappings, analyzer=rerun)
    except (HAImportError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/mapping-confirm")
async def mapping_confirm(body: dict, user=Depends(require_user)):
    _admin(user)
    required = ("source_kind", "source_identifier", "target_kind", "target_ref")
    if any(not body.get(key) for key in required): raise HTTPException(400, "source and target identity are required")
    if body.get("source_kind") in {"security_credential", "notification_destination", "speech_backend"} and not body.get("individually_reviewed"):
        raise HTTPException(409, "Sensitive mappings require individual review")
    try:
        existing = await mapping_registry.list_mappings(source_system="home_assistant", source_kind=body["source_kind"])
        match = next((row for row in existing if row.get("source_identifier") == body["source_identifier"]), None)
        confidence = str(body.get("confidence", "EXACT")).upper()
        if match:
            same_target = (match.get("target_kind") == body["target_kind"] and
                           str(match.get("target_ref")) == str(body["target_ref"]))
            if same_target and not body.get("replace"):
                # Confirmation is idempotent: do not rewrite validation or
                # update timestamps when the requested mapping is unchanged.
                return {**match, "no_change": True}
            if not body.get("replace"): raise HTTPException(409, "Mapping exists; set replace=true for an explicit replacement")
            result = await mapping_registry.update_mapping(match["mapping_id"], {"target_kind": body["target_kind"], "target_ref": body["target_ref"], "confidence": confidence, "origin": "USER_CONFIRMED", "notes": body.get("notes")}, actor=user.get("user"))
        else:
            # The server owns confirmation provenance.  Keep confidence as a
            # valid confidence value supplied by the reviewer.
            result = await mapping_registry.create_mapping({**body, "source_system": "home_assistant", "confidence": confidence, "origin": "USER_CONFIRMED"}, actor=user.get("user"))
        if result.get("status") != "VALID":
            raise HTTPException(409, "Mapping target is missing or unavailable")
        for alias in body.get("aliases") or []: await mapping_registry.add_alias(result["mapping_id"], alias)
        return result
    except HTTPException: raise
    except (ValueError, LookupError) as exc: raise HTTPException(400, str(exc)) from None


@router.post("/mapping-confirm/bulk")
async def mapping_confirm_bulk(body: dict, user=Depends(require_user)):
    _admin(user)
    items = body.get("mappings")
    if not isinstance(items, list) or not 1 <= len(items) <= 100: raise HTTPException(400, "Bulk mapping size must be 1..100")
    if any(item.get("source_kind") in {"security_credential", "notification_destination", "speech_backend"} or not item.get("individually_reviewed") for item in items):
        raise HTTPException(409, "Bulk confirmation excludes sensitive or unreviewed mappings")
    results = []
    for item in items: results.append(await mapping_confirm({**item, "replace": False}, user))
    return {"mappings": results, "count": len(results)}


@router.post("/apply")
async def apply(body: dict, user=Depends(require_user)):
    """Apply a previously returned plan while preserving staged state and provenance.

    The endpoint deliberately accepts the plan as data so the caller can review
    and retain it.  A dry run performs all eligibility checks and creates nothing.
    """
    _admin(user)
    plan = body.get("plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
        raise HTTPException(400, "A validated analysis plan is required")
    selected = body.get("selected_item_ids")
    if selected is None:
        selected = [item.get("source_id") for item in plan["items"] if item.get("eligibility") in ("READY", "READY_WITH_TRANSLATIONS")]
    selected = {str(x) for x in selected}
    blocked = [item for item in plan["items"] if str(item.get("source_id")) in selected and item.get("eligibility") not in ("READY", "READY_WITH_TRANSLATIONS")]
    if blocked:
        raise HTTPException(409, {"message": "Selected items are not eligible", "items": [{"source_id": x.get("source_id"), "eligibility": x.get("eligibility")} for x in blocked]})
    native = getattr(integrations, "native_primitives", None)
    engine = getattr(integrations, "automation_engine", None)
    if body.get("dry_run", True) and engine is None:
        raise HTTPException(503, "Native automation validator unavailable")
    if body.get("dry_run", True):
        report = {"dry_run": True, "selected": sorted(selected), "imported": [], "blocked": [], "failed": [], "dependencies": []}
    else:
        report = None
    if native is None or engine is None:
        if not body.get("dry_run", True):
            raise HTTPException(503, "Native automation services unavailable")
    if report is None:
        report = {"dry_run": False, "imported": [], "failed": [], "blocked": [], "already_imported": [], "provenance": []}
    # Re-analyze source objects with the caller's mapping before mutation.  This
    # prevents a hand-edited preview from bypassing compatibility checks.
    for item in plan["items"]:
        source_id = str(item.get("source_id"))
        if source_id not in selected:
            continue
        try:
            source_type = item.get("source_type")
            if source_type == "helpers":
                helper_type, _, helper_name = source_id.partition(".")
                reanalysis_source = {"helpers": {helper_type: {helper_name: item.get("source", {})}}}
            else:
                reanalysis_source = {source_type: {source_id: item.get("source", {})}}
            analyzed = analyze_home_assistant(reanalysis_source, mappings=await _analysis_mappings(body.get("mappings") or {}))
            if getattr(integrations, "registry", None) is not None:
                analyzed = await enrich_plan(analyzed, integrations.registry.services)
            current = analyzed["items"][0]
            if current.get("eligibility") not in ("READY", "READY_WITH_TRANSLATIONS"):
                report["blocked"].append({"source_id": source_id, "reason": current.get("eligibility")}); continue
            preview = current.get("preview") or {}
            async with db.acquire() as conn:
                staged = await conn.fetchrow("""SELECT * FROM ha_migration_items
                    WHERE source_system='home_assistant' AND source_kind='automation' AND source_identifier=$1""", source_id)
            if not staged:
                raise LookupError("staged automation source is no longer present")
            source_enabled = bool(staged["source_enabled"])
            existing_ref = staged["imported_native_ref"]
            if existing_ref:
                async with db.acquire() as conn:
                    existing = await conn.fetchrow("SELECT automation_id FROM automations WHERE automation_id=$1", existing_ref)
                if existing:
                    report["already_imported"].append({"source_id": source_id, "staged_id": str(staged["staged_id"]), "native_ref": str(existing_ref), "status": "NO_CHANGE"})
                    continue
                async with db.acquire() as conn:
                    await conn.execute("UPDATE ha_migration_items SET lifecycle_status='HA_IMPORT_STALE',updated_at=now() WHERE staged_id=$1", staged["staged_id"])
                raise RuntimeError("staged record has stale imported native ref")
            if body.get("dry_run", False):
                definition = {"name": preview.get("name", source_id), "description": preview.get("description"),
                              "enabled": source_enabled, "mode": preview.get("mode", "single"),
                              "max_runs": min(int(preview.get("max_runs", 10)), 10),
                              "triggers": preview.get("triggers") or [], "conditions": preview.get("conditions"),
                              "actions": preview.get("actions") or []}
                normalized = await engine.store.validate(definition, allow_planned=True)
                helpers = current.get("planned_native_helpers") or preview.get("native_objects_to_create", []) + preview.get("native_objects_to_reuse", [])
                report["dependencies"].append({"source_id": source_id, "staged_id": str(staged["staged_id"]), "helpers": [h.get("source_identity") for h in helpers], "helper_order": [h.get("source_identity") for h in helpers], "enabled": source_enabled})
                report["imported"].append({"source_id": source_id, "status": "validated", "enabled": normalized["enabled"], "helper_count": len(helpers)})
                continue
            if source_type == "scripts":
                row = await native.create_script(preview.get("name", source_id), preview.get("actions", []), description=preview.get("description"), mode=preview.get("mode", "single"), max_runs=min(int(preview.get("max_runs", 10)), 10), entity_id=f"script.{_slug(source_id)}")
            elif source_type == "scenes":
                targets = preview.get("targets", [])
                row = await native.create_scene(preview.get("name", source_id), targets, description=preview.get("description"), entity_id=f"scene.{_slug(source_id)}")
            elif source_type == "helpers":
                row = await native.create_helper(preview["helper_type"], preview["name"], preview.get("config", {}), entity_id=preview["entity_id"])
            else:
                row = await _apply_automation(engine, native, staged, current, preview, source_enabled)
            native_id = str(row.get("script_id", row.get("scene_id", row.get("automation_id", ""))))
            report["imported"].append({"source_id": source_id, "staged_id": str(staged["staged_id"]), "native_id": native_id, "enabled": source_enabled, "status": "CREATED"})
            report["provenance"].append({"source_system": "home_assistant", "source_type": source_type, "source_id": source_id, "staged_id": str(staged["staged_id"]), "source_fingerprint": item.get("source_fingerprint"), "native_ref": native_id})
        except Exception as exc:
            report["failed"].append({"source_id": source_id, "error": type(exc).__name__, "message": str(exc)})
    return report


def _slug(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "imported"


def _materialize_helpers(value, refs):
    if isinstance(value, dict):
        planned = value.get("planned_helper")
        if planned and planned in refs:
            return refs[planned]
        return {key: _materialize_helpers(item, refs) for key, item in value.items()}
    if isinstance(value, list):
        return [_materialize_helpers(item, refs) for item in value]
    return value


async def _helper_refs(native, planned):
    refs, mappings, created_helpers = {}, [], []
    async with db.acquire() as conn:
        existing_maps = await conn.fetch("""SELECT * FROM migration_mappings
            WHERE source_system='home_assistant' AND source_kind='helper' AND origin='IMPORT_PLANNED'""")
    by_source = {str(row["source_identifier"]): row for row in existing_maps}
    for helper in planned:
        identity = str(helper.get("source_identity") or "")
        if not identity:
            continue
        mapped = by_source.get(identity)
        if mapped:
            async with db.acquire() as conn:
                target = await conn.fetchrow("SELECT entity_ref,helper_type FROM native_helpers WHERE entity_ref=$1", int(mapped["target_ref"]))
            if not target or target["helper_type"] != helper.get("helper_type"):
                raise RuntimeError("helper mapping target is stale or collides")
            refs[identity] = int(target["entity_ref"])
            mappings.append({"source_identity": identity, "mapping_id": str(mapped["mapping_id"]), "status": "REUSED", "target_ref": int(target["entity_ref"])})
            continue
        entity_id = str(helper.get("proposed_entity_id") or identity)
        async with db.acquire() as conn:
            collision = await conn.fetchrow("SELECT entity_ref,helper_type FROM native_helpers WHERE entity_id=$1", entity_id)
        if collision and collision["helper_type"] != helper.get("helper_type"):
            raise RuntimeError("deterministic helper identity collides with an unrelated helper")
        if collision:
            ref = int(collision["entity_ref"])
            status = "CREATED_FOR_REUSE"
        else:
            created = await native.create_helper(helper["helper_type"], helper.get("name") or entity_id.split(".", 1)[-1], helper.get("config") or {}, entity_id=entity_id)
            ref = int(created["entity_ref"])
            status = "CREATED"
            created_helpers.append({"helper_id": str(created["helper_id"]), "entity_ref": ref, "source_identity": identity})
        try:
            mapping = await mapping_registry.create_mapping({
                "source_system": "home_assistant", "source_kind": "helper", "source_identifier": identity,
                "source_fingerprint": helper.get("source_fingerprint"), "target_kind": IMPORT_HELPER_TARGET_KIND,
                "target_ref": str(ref), "confidence": "EXACT", "origin": "IMPORT_PLANNED",
                "notes": "Importer-generated helper identity mapping"})
        except Exception:
            if status == "CREATED":
                try:
                    await native.delete_helper(created_helpers[-1]["helper_id"])
                except Exception:
                    pass
            raise
        refs[identity] = ref
        mappings.append({"source_identity": identity, "mapping_id": str(mapping["mapping_id"]), "status": status, "target_ref": ref})
        by_source[identity] = mapping
    return refs, mappings, created_helpers


async def _apply_automation(engine, native, staged, item, preview, source_enabled):
    planned = item.get("planned_native_helpers") or preview.get("native_objects_to_create", []) + preview.get("native_objects_to_reuse", [])
    refs, helper_mappings, created_helpers = await _helper_refs(native, planned)
    materialized = _materialize_helpers(preview, refs)
    definition = {"name": materialized.get("name", str(staged["source_identifier"])),
                  "description": materialized.get("description"), "enabled": source_enabled,
                  "mode": materialized.get("mode", "single"), "max_runs": min(int(materialized.get("max_runs", 10)), 10),
                  "triggers": materialized.get("triggers") or [], "conditions": materialized.get("conditions"),
                  "actions": materialized.get("actions") or []}
    normalized = await engine.store.validate(definition, allow_planned=False)
    row = None
    try:
        row = await engine.create_automation(normalized)
        async with db.acquire() as conn:
            await conn.execute("""UPDATE automations SET source_system='home_assistant', source_kind='automation',
                source_staged_id=$2, source_identifier=$3, source_fingerprint=$4, imported_at=now()
                WHERE automation_id=$1""", row["automation_id"], staged["staged_id"], str(staged["source_identifier"]), str(staged["source_fingerprint"]))
            await conn.execute("""UPDATE ha_migration_items SET imported_native_ref=$2, lifecycle_status='HA_IMPORTED', imported_at=now(), updated_at=now()
                WHERE staged_id=$1""", staged["staged_id"], str(row["automation_id"]))
    except Exception:
        if row:
            await engine.delete_automation(row["automation_id"])
        for mapping in helper_mappings:
            if mapping.get("status") in {"CREATED", "CREATED_FOR_REUSE"}:
                try:
                    await mapping_registry.delete_mapping(mapping["mapping_id"])
                except Exception:
                    pass
        for helper in created_helpers:
            try:
                await native.delete_helper(helper["helper_id"])
            except Exception:
                pass
        raise
    row["helper_mappings"] = helper_mappings
    return row
