from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from .integrations.runtime import runtime as integrations

router=APIRouter(prefix='/api/v1',dependencies=[Depends(require_user)])
def native():
    value=getattr(integrations,'native_primitives',None)
    if value is None: raise HTTPException(503,'Native primitives unavailable')
    return value
def role(user,mutate=False):
    if mutate and user.get('role')!='ADMIN': raise HTTPException(403,'ADMIN role required')
async def user(value=Depends(require_user)): return value

@router.get('/helpers')
async def helpers(user=Depends(user)): return {'helpers':await native().list_helpers()}
@router.post('/helpers')
async def create_helper(body:dict,user=Depends(user)):
    role(user,True)
    try: return await native().create_helper(body['helper_type'],body['name'],body.get('config',{}),entity_id=body.get('entity_id'))
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.get('/helpers/{helper_id}')
async def get_helper(helper_id:str,user=Depends(user)):
    try:return await native().get_helper(helper_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.put('/helpers/{helper_id}')
async def update_helper(helper_id:str,body:dict,user=Depends(user)):
    role(user,True)
    try:return await native().update_helper(helper_id,body.get('config',body))
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.delete('/helpers/{helper_id}')
async def delete_helper(helper_id:str,user=Depends(user)):
    role(user,True)
    try: await native().delete_helper(helper_id); return {'deleted':True}
    except LookupError as exc: raise HTTPException(404,str(exc))
    except ValueError as exc: raise HTTPException(409,str(exc))

@router.get('/scripts')
async def scripts(user=Depends(user)): return {'scripts':await native().list_scripts()}
@router.post('/scripts')
async def create_script(body:dict,user=Depends(user)):
    role(user,True)
    try:return await native().create_script(body['name'],body.get('actions',[]),description=body.get('description'),mode=body.get('mode','single'),max_runs=body.get('max_runs',10),inputs=body.get('inputs'),entity_id=body.get('entity_id'))
    except (KeyError,ValueError) as exc:raise HTTPException(400,str(exc))
@router.put('/scripts/{script_id}')
async def update_script(script_id:str,body:dict,user=Depends(user)):
    role(user,True)
    try:return await native().update_script(script_id,body)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.get('/scripts/{script_id}')
async def get_script(script_id:str,user=Depends(user)):
    try:return await native().get_script(script_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.post('/scripts/{script_id}/run')
async def run_script(script_id:str,body:dict|None=None,user=Depends(user)):
    role(user,True)
    try: row=await native().get_script(script_id); result=await native().registry.services.invoke('hcm_native','script','run',{'inputs':(body or {}).get('inputs',{})},target_entity_id=row['entity_ref']); return result
    except LookupError as exc:raise HTTPException(404,str(exc))
    except (ValueError,PermissionError) as exc:raise HTTPException(400,str(exc))
@router.get('/scripts/{script_id}/runs')
async def script_runs(script_id:str,limit:int=100,user=Depends(user)): return {'runs':await native().engine.list_script_runs(script_id,limit)}
@router.delete('/scripts/{script_id}')
async def delete_script(script_id:str,user=Depends(user)):
    role(user,True)
    try: await native().delete_script(script_id); return {'deleted':True}
    except LookupError as exc: raise HTTPException(404,str(exc))
    except ValueError as exc: raise HTTPException(409,str(exc))

@router.get('/scenes')
async def scenes(user=Depends(user)): return {'scenes':await native().list_scenes()}
@router.post('/scenes')
async def create_scene(body:dict,user=Depends(user)):
    role(user,True)
    try:return await native().create_scene(body['name'],body.get('targets',[]),description=body.get('description'),snapshot=bool(body.get('snapshot',False)),entity_id=body.get('entity_id'))
    except (KeyError,ValueError,LookupError) as exc:raise HTTPException(400,str(exc))
@router.put('/scenes/{scene_id}')
async def update_scene(scene_id:str,body:dict,user=Depends(user)):
    role(user,True)
    try:return await native().update_scene(scene_id,body)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.get('/scenes/{scene_id}')
async def get_scene(scene_id:str,user=Depends(user)):
    try:return await native().get_scene(scene_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.post('/scenes/{scene_id}/activate')
async def activate_scene(scene_id:str,body:dict|None=None,user=Depends(user)):
    role(user,True)
    try:
        row=await native().get_scene(scene_id)
        if (body or {}).get('dry_run'): return await native().activate_scene(row['entity_ref'],dry_run=True)
        return await native().registry.services.invoke('hcm_native','scene','turn_on',{},target_entity_id=row['entity_ref'])
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.delete('/scenes/{scene_id}')
async def delete_scene(scene_id:str,user=Depends(user)):
    role(user,True)
    try: await native().delete_scene(scene_id); return {'deleted':True}
    except LookupError as exc: raise HTTPException(404,str(exc))
    except ValueError as exc: raise HTTPException(409,str(exc))

@router.get('/references/entity/{entity_ref}')
async def entity_references(entity_ref:int,user=Depends(user)):
    return {'references':await native().references_entity(entity_ref)}

@router.get('/references/{kind}/{primitive_id}')
async def primitive_references(kind:str,primitive_id:str,user=Depends(user)):
    if kind not in {'helper','script','scene'}: raise HTTPException(404,'Unknown primitive kind')
    return {'references':await native().references_primitive(kind,primitive_id)}
