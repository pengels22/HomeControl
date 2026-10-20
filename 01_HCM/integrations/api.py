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

@router.post('/entities/{entity_ref}/capabilities')
async def entity_capability(entity_ref: int, body: dict, host=Depends(get_runtime)):
    domain, service = str(body.get('domain','')).split('.', 1) if '.' in str(body.get('domain','')) else (str(body.get('domain','')), str(body.get('service','')))
    if not domain or not service:
        raise HTTPException(400, 'domain and service are required')
    return await host.registry.services.validate_capability(entity_ref, domain, service, body.get('arguments') or {})

@router.get('/entities/{entity_ref}/capabilities')
async def entity_capabilities(entity_ref: int, host=Depends(get_runtime)):
    rows = await host.registry.inspect('services')
    entity_rows = await host.registry.inspect('entities')
    target = next((row for row in entity_rows if int(row['id']) == int(entity_ref)), None)
    if not target: raise HTTPException(404, 'Entity not found')
    return {'entity_ref': int(entity_ref), 'capabilities': [
        {'domain': row['domain'], 'service_name': row['service_name'], 'provider_id': row['provider_id'], 'target_requirements': row.get('target_requirements')}
        for row in rows if row['provider_id'] == target['provider_id'] and (not row.get('target_requirements') or target['domain'] in (row['target_requirements'].get('domains') or []))
    ]}


@router.get('/services')
async def services(provider_id: str | None=None,host=Depends(get_runtime)):
    return {'services':await host.registry.services.inspect(provider_id)}

@router.get('/events')
async def events(after_id:int=0,event_type:str|None=None,limit:int=100,host=Depends(get_runtime)):
    return {'events':await host.registry.events_after(after_id,event_type=event_type,limit=limit)}


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
