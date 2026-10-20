"""Authenticated Home Assistant migration endpoints.

Analysis accepts data supplied by the caller only.  It never reads a path or a
live HA instance.  Apply requires an ADMIN and an explicit plan plus selection;
the plan is revalidated before native stores are called.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_user
from .ha_importer import (
    BLOCKED_MAPPING, BLOCKED_SERVICE, BLOCKED_UNSUPPORTED, HAImportError,
    analyze_home_assistant, analyze_yaml, parse_registry_exports,
)
from .integrations.runtime import runtime as integrations
from . import mapping_registry
from .ha_capability_enrichment import enrich_plan
from .ha_mapping_review import build_mapping_queue, preview_mapping

router = APIRouter(prefix="/api/v1/import/home-assistant", dependencies=[Depends(require_user)])


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
    return plan


async def _mapping_candidates():
    try:
        rows = await integrations.registry.inspect("entities")
        devices = await integrations.registry.inspect("devices")
        result = [{"target_kind": "entity", "target_ref": row.get("id"), "entity_id": row.get("entity_id"),
                 "external_id": row.get("external_entity_id"), "name": row.get("display_name"),
                 "provider_id": row.get("provider_id"), "device_id": row.get("device_id")} for row in rows] + [
            {"target_kind": "device", "target_ref": row.get("id"), "external_id": row.get("external_device_id"),
             "name": row.get("display_name"), "provider_id": row.get("provider_id")} for row in devices]
        try:
            from . import notification_config
            result.extend({"target_kind": "notification_destination", "target_ref": row.get("destination_id"), "name": row.get("name")} for row in await notification_config.list_destinations())
            result.extend({"target_kind": "speech_backend", "target_ref": row.get("backend_id"), "name": row.get("name")} for row in await notification_config.list_backends())
        except Exception: pass
        try:
            from .zones import ZoneStore
            result.extend({"target_kind": "zone", "target_ref": row.get("zone_id"), "name": row.get("name")} for row in await ZoneStore().list())
        except Exception: pass
        return result
    except Exception:
        return []


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
        queue = build_mapping_queue(plan, durable_records=records, candidates=await _mapping_candidates(), limit=body.get("limit", 500))
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
        if match:
            if not body.get("replace"): raise HTTPException(409, "Mapping exists; set replace=true for an explicit replacement")
            result = await mapping_registry.update_mapping(match["mapping_id"], {"target_kind": body["target_kind"], "target_ref": body["target_ref"], "confidence": "USER_CONFIRMED", "origin": "USER_CONFIRMED", "notes": body.get("notes")}, actor=user.get("user"))
        else:
            result = await mapping_registry.create_mapping({**body, "source_system": "home_assistant", "confidence": "USER_CONFIRMED", "origin": "USER_CONFIRMED"}, actor=user.get("user"))
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
    """Apply a previously returned plan, with imported automations disabled.

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
    if body.get("dry_run", True):
        return {"dry_run": True, "selected": sorted(selected), "imported": [], "blocked": [], "failed": []}
    native = getattr(integrations, "native_primitives", None)
    engine = getattr(integrations, "automation_engine", None)
    if native is None or engine is None:
        raise HTTPException(503, "Native automation services unavailable")
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
            if body.get("dry_run", False):
                report["imported"].append({"source_id": source_id, "status": "validated"}); continue
            if source_type == "scripts":
                row = await native.create_script(preview.get("name", source_id), preview.get("actions", []), description=preview.get("description"), mode=preview.get("mode", "single"), max_runs=min(int(preview.get("max_runs", 10)), 10), entity_id=f"script.{_slug(source_id)}")
            elif source_type == "scenes":
                targets = preview.get("targets", [])
                row = await native.create_scene(preview.get("name", source_id), targets, description=preview.get("description"), entity_id=f"scene.{_slug(source_id)}")
            elif source_type == "helpers":
                row = await native.create_helper(preview["helper_type"], preview["name"], preview.get("config", {}), entity_id=preview["entity_id"])
            else:
                definition = {"name": preview.get("name", source_id), "description": preview.get("description"), "enabled": False, "mode": preview.get("mode", "single"), "max_runs": min(int(preview.get("max_runs", 10)), 10), "triggers": preview.get("triggers") or [], "conditions": preview.get("conditions"), "actions": preview.get("actions") or []}
                row = await engine.create_automation(definition)
            report["imported"].append({"source_id": source_id, "native_id": str(row.get("script_id", row.get("scene_id", row.get("automation_id", ""))))})
            report["provenance"].append({"source_system": "home_assistant", "source_type": source_type, "source_id": source_id, "source_fingerprint": item.get("source_fingerprint")})
        except Exception as exc:
            report["failed"].append({"source_id": source_id, "error": type(exc).__name__, "message": str(exc)})
    return report


def _slug(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "imported"
