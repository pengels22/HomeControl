"""Authenticated integration configuration endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from ..auth import require_user
from .runtime import runtime
from .config import ConfigInput, inspect, save, set_enabled, remove, safe_error
from .instances import list_instances, create as create_instance, set_enabled as set_instance_enabled, remove as remove_instance
from ..settings import settings
from .. import db
from . import oauth

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

@router.get('/providers')
async def providers():
    items=[]
    for entry in runtime.entries.values():
        info=entry.provider.info
        if info.internal and not settings.integration_show_test_providers: continue
        items.append({'provider_id':info.provider_id,'display_name':info.display_name,'description':info.description,
            'icon':info.icon,'setup_type':info.setup_type,'supports_multiple':info.supports_multiple,
            'capabilities':info.capabilities,'config_schema':info.config_schema,'config_flow':info.config_flow,
            'configured':entry.configured})
    return {'providers':items,'instances':await list_instances()}

@router.get('/instances')
async def instances(): return {'instances':await list_instances()}

@router.post('/instances')
async def add_instance(request:ConfigRequest,user=Depends(require_user)):
    admin(user)
    provider_id=request.config.pop('provider_id',None); name=request.config.pop('display_name',None)
    if not provider_id or not name: raise HTTPException(400,'provider_id and display_name are required')
    try: return {'instance_id':await create_instance(provider_id,name,request.config,credential_kind=request.credential_kind,credential=request.credential,actor=user['user'])}
    except Exception as exc: raise HTTPException(400,safe_error(exc)) from None

@router.post('/instances/{instance_id}/enable')
async def enable_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await set_instance_enabled(instance_id,True,user['user']); return {'ok':True}

@router.post('/instances/{instance_id}/disable')
async def disable_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await set_instance_enabled(instance_id,False,user['user']); return {'ok':True}

@router.delete('/instances/{instance_id}')
async def delete_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await remove_instance(instance_id,user['user']); return {'ok':True}

@router.get('/instances/{instance_id}/oauth/start')
async def oauth_start(instance_id:str, authorize_endpoint:str, client_id:str, redirect_uri:str, user=Depends(require_user)):
    admin(user)
    async with db.acquire() as conn:
        provider=await conn.fetchval('SELECT provider_id FROM integration_instances WHERE instance_id=$1',instance_id)
    if not provider: raise HTTPException(404,'Integration instance not found')
    return {'authorization_url':await oauth.authorization_url(provider,authorize_endpoint,client_id,redirect_uri,instance_id=instance_id)}

@router.get('/oauth/callback')
async def oauth_callback(provider_id:str, instance_id:str, state:str, redirect_uri:str, user=Depends(require_user)):
    await oauth.consume_state(provider_id,state,redirect_uri,instance_id)
    return RedirectResponse('/settings?integration='+instance_id+'&oauth=connected')
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
