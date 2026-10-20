from fastapi import APIRouter, Depends, HTTPException

from .auth import require_user
from .zones import ZoneStore

router = APIRouter(prefix='/api/v1/zones', dependencies=[Depends(require_user)])
store = ZoneStore()


def _admin(user):
    if user.get('role') != 'ADMIN': raise HTTPException(403, 'ADMIN role required')


@router.get('')
async def list_zones():
    return {'zones': await store.list()}


@router.get('/{zone_id}')
async def get_zone(zone_id: str):
    try: return await store.get(zone_id)
    except LookupError as exc: raise HTTPException(404, str(exc)) from None


@router.post('')
async def create_zone(body: dict, user=Depends(require_user)):
    _admin(user)
    try: return await store.create(body)
    except (TypeError, ValueError) as exc: raise HTTPException(400, str(exc)) from None


@router.patch('/{zone_id}')
async def update_zone(zone_id: str, body: dict, user=Depends(require_user)):
    _admin(user)
    try: return await store.update(zone_id, body)
    except LookupError as exc: raise HTTPException(404, str(exc)) from None
    except (TypeError, ValueError) as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{zone_id}/enable')
async def enable_zone(zone_id: str, user=Depends(require_user)):
    return await update_zone(zone_id, {'enabled': True}, user)


@router.post('/{zone_id}/disable')
async def disable_zone(zone_id: str, user=Depends(require_user)):
    return await update_zone(zone_id, {'enabled': False}, user)


@router.delete('/{zone_id}')
async def delete_zone(zone_id: str, user=Depends(require_user)):
    _admin(user)
    try: deleted = await store.delete(zone_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from None
    if not deleted: raise HTTPException(404, 'Zone not found')
    return {'deleted': True}
