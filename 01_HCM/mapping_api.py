"""Authenticated inspection and administration of durable migration mappings."""
from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from . import mapping_registry as mappings

router = APIRouter(prefix="/api/v1/mappings", dependencies=[Depends(require_user)])


def _admin(user):
    if user.get("role") != "ADMIN": raise HTTPException(403, "ADMIN role required")


@router.get("")
async def list_mapping_records(source_system: str | None = None, source_kind: str | None = None, status: str | None = None):
    return {"mappings": await mappings.list_mappings(source_system=source_system, source_kind=source_kind, status=status)}


@router.get("/source/{source_system}/{source_kind}/{source_identifier}")
async def source_mapping(source_system: str, source_kind: str, source_identifier: str):
    row = await mappings.resolve(source_system, source_kind, source_identifier)
    if not row: raise HTTPException(404, "Mapping not found")
    return row


@router.get("/{mapping_id}")
async def get_mapping(mapping_id: str):
    try: return await mappings.get_mapping(mapping_id)
    except (LookupError, ValueError) as exc: raise HTTPException(404, str(exc)) from None


@router.post("")
async def create_mapping(body: dict, user=Depends(require_user)):
    _admin(user)
    try: return await mappings.create_mapping(body, actor=user.get("user"))
    except (ValueError, LookupError) as exc: raise HTTPException(400, str(exc)) from None


@router.post("/bulk")
async def create_bulk(body: dict, user=Depends(require_user)):
    _admin(user)
    try: return {"mappings": await mappings.bulk_create(body.get("mappings"), actor=user.get("user"))}
    except (ValueError, LookupError) as exc: raise HTTPException(400, str(exc)) from None


@router.patch("/{mapping_id}")
async def update_mapping(mapping_id: str, body: dict, user=Depends(require_user)):
    _admin(user)
    try: return await mappings.update_mapping(mapping_id, body, actor=user.get("user"))
    except (ValueError, LookupError) as exc: raise HTTPException(400, str(exc)) from None


@router.post("/{mapping_id}/validate")
async def validate_mapping(mapping_id: str):
    try: return await mappings.validate_mapping(mapping_id)
    except (ValueError, LookupError) as exc: raise HTTPException(404, str(exc)) from None

@router.post("/{mapping_id}/aliases")
async def add_mapping_alias(mapping_id: str, body: dict, user=Depends(require_user)):
    _admin(user)
    if not body.get("alias_identifier"): raise HTTPException(400, "alias_identifier is required")
    try: return await mappings.add_alias(mapping_id, body["alias_identifier"], source_system=body.get("source_system"), source_kind=body.get("source_kind"))
    except (ValueError, LookupError) as exc: raise HTTPException(400, str(exc)) from None


@router.post("/{mapping_id}/invalidate")
async def invalidate_mapping(mapping_id: str, user=Depends(require_user)):
    _admin(user)
    try: return await mappings.invalidate_mapping(mapping_id, actor=user.get("user"))
    except (ValueError, LookupError) as exc: raise HTTPException(404, str(exc)) from None


@router.delete("/{mapping_id}")
async def delete_mapping(mapping_id: str, user=Depends(require_user)):
    _admin(user)
    try:
        await mappings.invalidate_mapping(mapping_id, actor=user.get("user"))
        return {"ok": True, "status": "INVALID"}
    except (ValueError, LookupError) as exc: raise HTTPException(404, str(exc)) from None
