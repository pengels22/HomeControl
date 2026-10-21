from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from .ha_importer import analyze_home_assistant, analyze_yaml
from .ha_staging import get_item, ingest_plan, list_items, update_source_enabled
from .ha_import_api import _analysis_mappings

router = APIRouter(prefix="/api/v1/import/home-assistant/staged", dependencies=[Depends(require_user)])


def _admin(user):
    if user.get("role") != "ADMIN": raise HTTPException(403, "ADMIN role required")


@router.get("")
async def staged_list(search: str | None = None, source_kind: str | None = None, compatibility: str | None = None,
                      source_enabled: bool | None = None, limit: int = 200, offset: int = 0):
    return await list_items(search=search, source_kind=source_kind, compatibility=compatibility, source_enabled=source_enabled, limit=limit, offset=offset)


@router.get("/{staged_id}")
async def staged_detail(staged_id: str):
    try: return await get_item(staged_id)
    except (LookupError, ValueError): raise HTTPException(404, "Staged migration item not found") from None


@router.post("/ingest")
async def staged_ingest(body: dict, user=Depends(require_user)):
    _admin(user)
    try:
        mappings = await _analysis_mappings(body.get("mappings") or {})
        if body.get("automations_yaml") is not None:
            plan = analyze_yaml(automations=body.get("automations_yaml"), mappings=mappings)
        else:
            plan = analyze_home_assistant({"automations": body.get("automations", [])}, mappings=mappings)
        return await ingest_plan(plan, runtime_state=body.get("runtime_state"), state_provenance=body.get("state_provenance", "HA_RUNTIME_STATE"))
    except (TypeError, ValueError) as exc: raise HTTPException(400, str(exc)) from None


@router.patch("/{staged_id}")
async def staged_update(staged_id: str, body: dict, user=Depends(require_user)):
    _admin(user)
    if "source_enabled" not in body or not isinstance(body["source_enabled"], bool): raise HTTPException(400, "source_enabled must be boolean")
    try: return await update_source_enabled(staged_id, body["source_enabled"])
    except (LookupError, ValueError): raise HTTPException(404, "Staged migration item not found") from None
