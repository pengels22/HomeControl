from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from .automation import AutomationValidationError
from .integrations.runtime import runtime as integrations
import yaml

router=APIRouter(prefix='/api/v1/automations',dependencies=[Depends(require_user)])

def _engine():
    return getattr(integrations,'automation_engine',None)

def _role(user, mutate=False):
    if mutate and user.get('role')!='ADMIN': raise HTTPException(403,'ADMIN role required')

async def _user(user=Depends(require_user)): return user

@router.get('')
async def list_automations(user=Depends(_user)):
    return {'automations':await _engine().store.list()}

@router.post('')
async def create_automation(body:dict,user=Depends(_user)):
    _role(user,True)
    try: return await _engine().create_automation(_definition(body))
    except (AutomationValidationError,ValueError) as exc: raise HTTPException(400,str(exc))

@router.get('/{automation_id}')
async def get_automation(automation_id:str,user=Depends(_user)):
    try: return await _engine().inspect_automation(automation_id)
    except LookupError as exc: raise HTTPException(404,str(exc))

@router.put('/{automation_id}')
async def update_automation(automation_id:str,body:dict,user=Depends(_user)):
    _role(user,True)
    try: return await _engine().update_automation(automation_id,_definition(body))
    except LookupError as exc: raise HTTPException(404,str(exc))
    except (AutomationValidationError,ValueError) as exc: raise HTTPException(400,str(exc))


def _definition(body: dict) -> dict:
    if not isinstance(body, dict): raise ValueError("Automation definition must be an object")
    if "yaml" not in body: return body
    try:
        parsed = yaml.safe_load(body["yaml"])
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid HCM YAML: {exc}") from None
    if not isinstance(parsed, dict): raise ValueError("HCM YAML must contain an automation object")
    for key in ("name", "description", "enabled", "mode"):
        if key in body: parsed[key] = body[key]
    return parsed

@router.post('/{automation_id}/enable')
async def enable(automation_id:str,user=Depends(_user)):
    _role(user,True); return await _engine().set_enabled(automation_id,True)

@router.post('/{automation_id}/disable')
async def disable(automation_id:str,user=Depends(_user)):
    _role(user,True); return await _engine().set_enabled(automation_id,False)

@router.delete('/{automation_id}')
async def delete(automation_id:str,user=Depends(_user)):
    _role(user,True)
    if not await _engine().delete_automation(automation_id): raise HTTPException(404,'Automation not found')
    return {'deleted':True}

@router.get('/{automation_id}/runs')
async def runs(automation_id:str,limit:int=100,user=Depends(_user)):
    return {'runs':await _engine().list_runs(automation_id,limit)}

@router.get('/{automation_id}/runs/{run_id}')
async def run(automation_id:str,run_id:str,user=Depends(_user)):
    try: return await _engine().get_run(run_id)
    except LookupError as exc: raise HTTPException(404,str(exc))

@router.post('/{automation_id}/run')
async def manual_run(automation_id:str,body:dict|None=None,user=Depends(_user)):
    _role(user,True)
    try: automation=await _engine().store.get(automation_id)
    except LookupError as exc: raise HTTPException(404,str(exc))
    if not automation['enabled']: raise HTTPException(409,'Automation is disabled')
    run_id=await _engine().trigger(automation,source='manual',dry_run=bool((body or {}).get('dry_run',False)))
    if run_id is None: raise HTTPException(409,'Automation run limit reached')
    return {'run_id':str(run_id),'trigger_source':'manual','dry_run':bool((body or {}).get('dry_run',False))}
