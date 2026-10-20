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
from . import secrets as secret_store
from .factory import provider_factory
from .http import ProviderHTTP

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
    for provider_id,provider_type in provider_factory.types.items():
        info=provider_type.info
        entry=runtime.entries.get(provider_id)
        if info.internal and not settings.integration_show_test_providers: continue
        items.append({'provider_id':info.provider_id,'display_name':info.display_name,'description':info.description,
            'icon':info.icon,'setup_type':info.setup_type,'supports_multiple':info.supports_multiple,
            'capabilities':info.capabilities,'config_schema':info.config_schema,'config_flow':info.config_flow,
            'configured':entry.configured if entry else False})
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
    admin(user); await set_instance_enabled(instance_id,True,user['user'])
    if instance_id not in runtime.instances:
        async with db.acquire() as conn: row=await conn.fetchrow('SELECT provider_id,configured FROM integration_instances WHERE instance_id=$1',instance_id)
        if row:
            runtime.attach_instance(instance_id,row['provider_id'],runtime.registry.context(row['provider_id'],instance_id),enabled=True,configured=row['configured'])
    if instance_id in runtime.instances: await runtime.start_instance(instance_id)
    return {'ok':True}

@router.post('/instances/{instance_id}/disable')
async def disable_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await set_instance_enabled(instance_id,False,user['user']); await runtime.stop_instance(instance_id); return {'ok':True}

@router.post('/instances/{instance_id}/reload')
async def reload_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await runtime.reload_instance(instance_id); return {'ok':True}

@router.delete('/instances/{instance_id}')
async def delete_instance(instance_id:str,user=Depends(require_user)):
    admin(user); await runtime.stop_instance(instance_id); runtime.instances.pop(instance_id,None); await remove_instance(instance_id,user['user']); return {'ok':True}

@router.get('/instances/{instance_id}/oauth/start')
async def oauth_start(instance_id:str, authorize_endpoint:str, client_id:str, redirect_uri:str, user=Depends(require_user)):
    admin(user)
    async with db.acquire() as conn:
        provider=await conn.fetchval('SELECT provider_id FROM integration_instances WHERE instance_id=$1',instance_id)
    if not provider: raise HTTPException(404,'Integration instance not found')
    info=provider_factory.types.get(provider).info
    scopes=(info.config_flow or {}).get('scopes',())
    return {'authorization_url':await oauth.authorization_url(provider,authorize_endpoint,client_id,redirect_uri,scopes=scopes,instance_id=instance_id)}

@router.get('/oauth/callback')
async def oauth_callback(provider_id:str, instance_id:str, state:str, redirect_uri:str, code:str|None=None, user=Depends(require_user)):
    await oauth.consume_state(provider_id,state,redirect_uri,instance_id)
    if code:
        async with db.acquire() as conn:
            row=await conn.fetchrow('SELECT provider_id,config,credential_ref FROM integration_instances WHERE instance_id=$1',instance_id)
        if not row or row['provider_id']!=provider_id: raise HTTPException(404,'Integration instance not found')
        config=row['config'] or {}
        if isinstance(config,str): config=__import__('json').loads(config)
        client_id=config.get('client_id'); client_secret=await secret_store.get(row['credential_ref']) if row['credential_ref'] else None
        info=provider_factory.types.get(provider_id).info
        metadata=oauth.OAuthMetadata('https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token',tuple((info.config_flow or {}).get('scopes',())))
        http=ProviderHTTP(timeout=15)
        async def request(url,data,auth_style):
            return (await http.json('POST',url,form_body=data,headers={'Accept':'application/json'}))[0]
        try:
            token=await oauth.OAuthHTTPClient(request).exchange(metadata,code,client_id,client_secret,redirect_uri)
        finally: await http.close()
        bundle={'access_token':token.access_token,'refresh_token':token.refresh_token,'token_type':token.token_type,'scopes':list(token.scopes)}
        ref=await secret_store.put(provider_id,'oauth_access_token',bundle,metadata={'expires_at':token.expires_at})
        async with db.acquire() as conn:
            await conn.execute("UPDATE integration_instances SET account_ref=$2,configured=true,status='connected',last_error=NULL,last_success=now(),updated_at=now() WHERE instance_id=$1",instance_id,ref)
        if instance_id in runtime.instance_contexts:
            runtime.instance_contexts[instance_id].account_ref=ref
            runtime.instance_contexts[instance_id].credential_ref=row['credential_ref']
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
