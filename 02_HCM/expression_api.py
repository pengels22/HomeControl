from fastapi import APIRouter, Depends, HTTPException
from .auth import require_user
from .expressions import ExpressionError, Undefined
from .integrations.runtime import runtime as integrations

router=APIRouter(prefix='/api/v1/expressions',dependencies=[Depends(require_user)])

def _safe_context(value,depth=0):
    if depth>8: raise HTTPException(400,'Context nesting limit exceeded')
    if isinstance(value,dict):
        if any(str(k).startswith('_') for k in value): raise HTTPException(400,'Private context keys are forbidden')
        return {str(k):_safe_context(v,depth+1) for k,v in value.items()}
    if isinstance(value,list):
        if len(value)>100: raise HTTPException(400,'Context collection is too large')
        return [_safe_context(v,depth+1) for v in value]
    if value is None or isinstance(value,(bool,int,float,str)): return value
    raise HTTPException(400,'Unsupported context value')

@router.post('/test')
async def test_expression(body:dict,user=Depends(require_user)):
    source=body.get('expression',body.get('template'))
    syntax=body.get('syntax','jinja' if isinstance(source,str) and '{{' in source else 'native')
    if not isinstance(source,str): raise HTTPException(400,'expression is required')
    engine=getattr(integrations,'automation_engine',None)
    if engine is None: raise HTTPException(503,'Automation Engine unavailable')
    try:
        compiled=engine.expressions.compile(source,syntax=syntax)
        result=await engine.expressions.evaluate_compiled(compiled,_safe_context(body.get('context',{})))
        return {'valid':True,'result':None if result is Undefined else result,'result_type':type(result).__name__,'dependencies':engine.expressions.dependencies(compiled),'ast':compiled}
    except ExpressionError as exc:
        return {'valid':False,'error_category':exc.category,'error':str(exc)}
