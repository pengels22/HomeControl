"""Authenticated integration configuration endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from ..auth import require_user
from .runtime import runtime
from .config import ConfigInput, inspect, save, set_enabled, remove, safe_error

router=APIRouter(prefix='/api/v1/integrations',dependencies=[Depends(require_user)])
class ConfigRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config: dict=Field(default_factory=dict)
    credential_kind: str|None=None
    credential: object|None=None
def admin(user):
    if user.get('role')!='ADMIN': raise HTTPException(403,'ADMIN role required')
@router.get('/configuration')
async def configurations(): return {'integrations':await inspect()}
@router.put('/{provider_id}/configuration')
async def configure(provider_id:str, request:ConfigRequest, user=Depends(require_user)):
    admin(user); entry=runtime.entries.get(provider_id)
    if not entry: raise HTTPException(404,'Provider not loaded')
    try:
        await entry.provider.validate_config(request.config)
        if request.credential is not None: await entry.provider.validate_credentials(request.credential)
        result=await save(entry.provider,ConfigInput(**request.model_dump()),actor=user['user'])
        if entry.status in {'connected','degraded'}: await runtime.reload(provider_id)
        return result
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400,safe_error(exc)) from None
@router.post('/{provider_id}/enable')
async def enable(provider_id:str,user=Depends(require_user)):
    admin(user); await set_enabled(provider_id,True,user['user']); return {'ok':True}
@router.post('/{provider_id}/disable')
async def disable(provider_id:str,user=Depends(require_user)):
    admin(user); await set_enabled(provider_id,False,user['user']); return {'ok':True}
@router.post('/{provider_id}/reload')
async def reload(provider_id:str,user=Depends(require_user)):
    admin(user)
    try: await runtime.reload(provider_id); return {'ok':True}
    except Exception as exc: raise HTTPException(400,safe_error(exc)) from None
@router.delete('/{provider_id}')
async def delete(provider_id:str,user=Depends(require_user)):
    admin(user); await remove(provider_id,user['user']); runtime.entries.pop(provider_id,None); return {'ok':True}
