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
    analyze_home_assistant, analyze_yaml,
)
from .integrations.runtime import runtime as integrations

router = APIRouter(prefix="/api/v1/import/home-assistant", dependencies=[Depends(require_user)])


def _admin(user: dict[str, str]):
    if user.get("role") != "ADMIN":
        raise HTTPException(403, "ADMIN role required")


@router.post("/analyze")
async def analyze(body: dict, user=Depends(require_user)):
    _admin(user)
    try:
        mappings = body.get("mappings") or {}
        if any(k in body for k in ("automations_yaml", "scripts_yaml", "scenes_yaml")):
            return analyze_yaml(automations=body.get("automations_yaml"), scripts=body.get("scripts_yaml"), scenes=body.get("scenes_yaml"), mappings=mappings)
        sources = body.get("sources", body.get("source", body))
        return analyze_home_assistant(sources, mappings=mappings)
    except HAImportError as exc:
        raise HTTPException(400, str(exc)) from None
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


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
            analyzed = analyze_home_assistant(reanalysis_source, mappings=body.get("mappings") or {})
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
                row = await engine.store.create(definition)
            report["imported"].append({"source_id": source_id, "native_id": str(row.get("script_id", row.get("scene_id", row.get("automation_id", ""))))})
            report["provenance"].append({"source_system": "home_assistant", "source_type": source_type, "source_id": source_id, "source_fingerprint": item.get("source_fingerprint")})
        except Exception as exc:
            report["failed"].append({"source_id": source_id, "error": type(exc).__name__, "message": str(exc)})
    return report


def _slug(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "imported"
