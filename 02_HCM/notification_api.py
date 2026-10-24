from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from . import notification_config as cfg

router=APIRouter(prefix='/api/v1/notification-config',dependencies=[Depends(require_user)])

def admin(user):
    if user.get('role')!='ADMIN': raise HTTPException(403,'ADMIN role required')

@router.get('/destinations')
async def destinations(): return {'destinations':await cfg.list_destinations()}
@router.post('/destinations')
async def create_destination(body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.create_destination(body['name'],body['destination_type'],body.get('config'),enabled=body.get('enabled',True),configured=body.get('configured',False),credential_ref=body.get('credential_ref'))
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.put('/destinations/{destination_id}')
async def update_destination(destination_id:str,body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.update_destination(destination_id,body)
    except (LookupError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.delete('/destinations/{destination_id}')
async def delete_destination(destination_id:str,user=Depends(require_user)):
    admin(user)
    try: return {'deleted':await cfg.delete_destination(destination_id)}
    except (LookupError,ValueError) as exc: raise HTTPException(409,str(exc))

@router.get('/backends')
async def backends(): return {'backends':await cfg.list_backends()}
@router.post('/backends')
async def create_backend(body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.create_backend(body['name'],body['backend_type'],body.get('config'),enabled=body.get('enabled',True),configured=body.get('configured',False),languages=body.get('languages'),voices=body.get('voices'),credential_ref=body.get('credential_ref'))
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.put('/backends/{backend_id}')
async def update_backend(backend_id:str,body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.update_backend(backend_id,body)
    except (LookupError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.delete('/backends/{backend_id}')
async def delete_backend(backend_id:str,user=Depends(require_user)):
    admin(user)
    try: return {'deleted':await cfg.delete_backend(backend_id)}
    except (LookupError,ValueError) as exc: raise HTTPException(409,str(exc))

@router.post('/mappings/notification')
async def notification_mapping(body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.set_notification_mapping(body['source_service'],body['destination_id'])
    except (KeyError,LookupError,ValueError) as exc: raise HTTPException(400,str(exc))
@router.post('/mappings/speech')
async def speech_mapping(body:dict,user=Depends(require_user)):
    admin(user)
    try: return await cfg.set_speech_mapping(body['source_entity'],body['backend_id'])
    except (KeyError,LookupError,ValueError) as exc: raise HTTPException(400,str(exc))
