"""Inspection only: no provider configuration, credentials or action endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from ..auth import require_user
from .runtime import runtime

router=APIRouter(prefix='/api/v1/integrations',dependencies=[Depends(require_user)])


def get_runtime():
    return runtime


@router.get('')
async def integrations(host=Depends(get_runtime)):
    return {'integrations':await host.registry.inspect('integrations')}


@router.get('/devices')
async def devices(provider_id: str | None=None,host=Depends(get_runtime)):
    return {'devices':await host.registry.inspect('devices',provider_id)}


@router.get('/entities')
async def entities(provider_id: str | None=None,host=Depends(get_runtime)):
    return {'entities':await host.registry.inspect('entities',provider_id)}


@router.get('/services')
async def services(provider_id: str | None=None,host=Depends(get_runtime)):
    return {'services':await host.registry.services.inspect(provider_id)}


@router.get('/{provider_id}/status')
async def status(provider_id: str,host=Depends(get_runtime)):
    providers=await host.registry.inspect('integrations',provider_id)
    if not providers:
        raise HTTPException(404,'Provider not found')
    row=providers[0]
    entry=host.entries.get(provider_id)
    return {**row,'runtime_status':entry.status if entry else 'not_loaded',
            'device_count':len(await host.registry.inspect('devices',provider_id)),
            'entity_count':len(await host.registry.inspect('entities',provider_id))}


@router.get('/{provider_id}/diagnostics')
async def diagnostics(provider_id: str,host=Depends(get_runtime)):
    if provider_id not in host.entries:
        raise HTTPException(404,'Provider not loaded')
    return await host.diagnostics(provider_id)
