"""Bounded, provider-neutral expression/template engine.

Expressions are compiled to an explicit normalized AST and interpreted without
Python evaluation, imports, object traversal, I/O, or callable escape paths.
"""
from __future__ import annotations
import ast, asyncio, json, math, re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo
from . import db

MAX_SOURCE=4096; MAX_NODES=100; MAX_DEPTH=20; MAX_COLLECTION=100; MAX_RENDERED=8192
ALLOWED_FUNCTIONS={'states','is_state','state_attr','float','int','string','bool','default','lower','upper','trim','replace','length','count','first','last','join','list','min','max','round','abs','now','utcnow','today_at','duration','as_timestamp','as_datetime','as_local','startswith','endswith'}
class ExpressionError(ValueError):
    def __init__(self, category, message): self.category=category; super().__init__(message)
class UndefinedType:
    def __repr__(self): return 'undefined'
    def __bool__(self): return False
    def __str__(self): return ''
    def __eq__(self, other): return isinstance(other,UndefinedType)
    def __lt__(self, other): return False
    def __le__(self, other): return False
    def __gt__(self, other): return False
    def __ge__(self, other): return False
Undefined=UndefinedType()

@dataclass(frozen=True)
class Snapshot:
    entity_ref: int|None
    entity_id: str|None
    state: Any
    attributes: Mapping[str,Any]
    availability: bool=True
    timestamp: Any=None

class ExpressionEngine:
    def __init__(self, *, timezone_name='UTC', resolver=None):
        self.timezone=ZoneInfo(timezone_name); self.resolver=resolver; self.cache={}
    def compile(self, source, *, syntax='native'):
        if not isinstance(source,str) or len(source)>MAX_SOURCE: raise ExpressionError('resource limit','Expression is too long')
        key=(syntax,source)
        if key in self.cache: return self.cache[key]
        if syntax not in ('native','jinja'): raise ExpressionError('unsupported','Unknown syntax mode')
        if syntax=='jinja' and '{%' in source: raise ExpressionError('unsupported','Jinja control blocks are unsupported')
        text=source.strip()
        pure=False
        if syntax=='jinja':
            matches=re.findall(r'{{\s*(.*?)\s*}}',source,re.S)
            if not matches: return self._cache(key,('literal',source))
            if len(matches)==1 and re.fullmatch(r'\s*{{\s*.*?\s*}}\s*',source,re.S): text=matches[0]; pure=True
            else: return self._cache(key,('template',[(part, expr) for part,expr in self._parts(source)]))
        text=self._filters_to_calls(text)
        # HA's Jinja tests used by the compatibility surface have explicit,
        # bounded equivalents in the expression AST.  Keep this normalization
        # deliberately small; general Jinja syntax remains unsupported.
        text=re.sub(r"\bis\s+not\s+none\b", "!= None", text)
        text=re.sub(r"\bis\s+none\b", "== None", text)
        try: tree=ast.parse(text,mode='eval').body
        except SyntaxError as exc: raise ExpressionError('parse','Invalid expression syntax') from None
        node_count=[0]
        normalized=self._convert(tree,0,node_count)
        result=('expression',normalized,pure)
        return self._cache(key,result)
    def _cache(self,key,value):
        if len(self.cache)>=128: self.cache.pop(next(iter(self.cache)))
        self.cache[key]=value; return value
    def _parts(self,source):
        out=[]; pos=0
        for match in re.finditer(r'{{\s*(.*?)\s*}}',source,re.S):
            if match.start()>pos: out.append((source[pos:match.start()],None))
            out.append(('',match.group(1))); pos=match.end()
        if pos<len(source): out.append((source[pos:],None))
        return out
    def _filters_to_calls(self,text):
        # Translate bounded HA filter chains, including list literals, without
        # embedding a Jinja parser or evaluating arbitrary syntax.
        if '|' not in text:
            return text
        pattern=re.compile(r"(\[[^\[\]]*\]|\b[A-Za-z_][A-Za-z0-9_]*\([^()]*\)|\b[A-Za-z_][A-Za-z0-9_]*|\([^()]+\))\s*\|\s*([A-Za-z_][A-Za-z0-9_]*)(?:\(([^()]*)\))?")
        previous=None
        while '|' in text and text!=previous:
            previous=text
            def repl(match):
                operand,name,args=match.group(1),match.group(2),match.group(3)
                return f"{name}({operand}{','+args if args else ''})"
            text=pattern.sub(repl,text)
        if '|' in text: raise ExpressionError('unsupported','Invalid filter syntax')
        return text
    def _split_top(self,text,delimiter):
        out=[]; start=0; depth=0; quote=None
        for i,ch in enumerate(text):
            if quote:
                if ch==quote and (i==0 or text[i-1]!='\\'): quote=None
            elif ch in "'\"": quote=ch
            elif ch in '([{': depth+=1
            elif ch in ')]}': depth-=1
            elif ch==delimiter and depth==0: out.append(text[start:i]); start=i+1
        out.append(text[start:]); return out
    def _convert(self,n,depth,count):
        count[0]+=1
        if count[0]>MAX_NODES or depth>MAX_DEPTH: raise ExpressionError('resource limit','Expression AST is too large')
        if isinstance(n,ast.Constant):
            if n.value is None or isinstance(n.value,(bool,int,float,str)): return ('literal',n.value)
            raise ExpressionError('unsupported','Unsupported literal type')
        if isinstance(n,ast.Name):
            if n.id.startswith('_'): raise ExpressionError('unsupported','Private names are forbidden')
            return ('name',n.id)
        if isinstance(n,ast.List):
            if len(n.elts)>MAX_COLLECTION: raise ExpressionError('resource limit','Collection is too large')
            return ('list',[self._convert(x,depth+1,count) for x in n.elts])
        if isinstance(n,ast.Tuple): return ('list',[self._convert(x,depth+1,count) for x in n.elts])
        if isinstance(n,ast.Dict):
            if len(n.keys)>MAX_COLLECTION: raise ExpressionError('resource limit','Mapping is too large')
            return ('mapping',[(self._convert(k,depth+1,count),self._convert(v,depth+1,count)) for k,v in zip(n.keys,n.values)])
        if isinstance(n,ast.UnaryOp) and type(n.op) in (ast.Not,ast.USub,ast.UAdd): return ('unary',type(n.op).__name__,self._convert(n.operand,depth+1,count))
        if isinstance(n,ast.BinOp) and type(n.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod,ast.FloorDiv): return ('binary',type(n.op).__name__,self._convert(n.left,depth+1,count),self._convert(n.right,depth+1,count))
        if isinstance(n,ast.BoolOp) and type(n.op) in (ast.And,ast.Or): return ('bool',type(n.op).__name__,[self._convert(x,depth+1,count) for x in n.values])
        if isinstance(n,ast.Compare):
            if len(n.ops)!=1: raise ExpressionError('unsupported','Chained comparisons are unsupported')
            op=n.ops[0]
            if type(op) not in (ast.Eq,ast.NotEq,ast.Gt,ast.GtE,ast.Lt,ast.LtE,ast.In,ast.NotIn): raise ExpressionError('unsupported','Comparison is unsupported')
            return ('compare',type(op).__name__,self._convert(n.left,depth+1,count),self._convert(n.comparators[0],depth+1,count))
        if isinstance(n,ast.IfExp): return ('if',self._convert(n.test,depth+1,count),self._convert(n.body,depth+1,count),self._convert(n.orelse,depth+1,count))
        if isinstance(n,ast.Call):
            if not isinstance(n.func,ast.Name) or n.func.id.startswith('_') or n.func.id not in ALLOWED_FUNCTIONS: raise ExpressionError('unknown function',f'Unknown function: {getattr(n.func,"id","")}')
            if n.keywords:
                if n.func.id!='duration' or any(k.arg is None for k in n.keywords): raise ExpressionError('unsupported','Keyword arguments are only supported by duration')
                mapping=('mapping',[(('literal',k.arg),self._convert(k.value,depth+1,count)) for k in n.keywords])
                return ('call',n.func.id,[mapping]+[self._convert(x,depth+1,count) for x in n.args])
            return ('call',n.func.id,[self._convert(x,depth+1,count) for x in n.args])
        if isinstance(n,ast.Subscript):
            return ('index',self._convert(n.value,depth+1,count),self._convert(n.slice,depth+1,count))
        if isinstance(n,ast.Attribute):
            if n.attr.startswith('_'): raise ExpressionError('unsupported','Private attributes are forbidden')
            return ('attribute',self._convert(n.value,depth+1,count),n.attr)
        raise ExpressionError('unsupported',f'Unsupported syntax: {type(n).__name__}')
    def dependencies(self,compiled):
        found=set()
        if isinstance(compiled,tuple) and compiled[0]=='template':
            for _,expr in compiled[1]:
                if expr:
                    try: compiled_expr=self.compile(expr,syntax='native')
                    except ExpressionError: continue
                    found.update(self.dependencies(compiled_expr))
            return sorted(found)
        def walk(n):
            if isinstance(n,tuple):
                if n[0]=='call' and n[1] in ('states','is_state','state_attr') and len(n[2]) and n[2][0][0]=='literal' and isinstance(n[2][0][1],str): found.add(n[2][0][1])
                for x in n[1:]: walk(x)
            elif isinstance(n,list):
                for x in n: walk(x)
        walk(compiled); return sorted(found)
    async def evaluate(self,source,*,context=None,syntax='native'):
        compiled=self.compile(source,syntax=syntax)
        return await self.evaluate_compiled(compiled,context or {})
    async def evaluate_compiled(self,c,context):
        if c[0]=='literal': return c[1]
        if c[0]=='template':
            chunks=[]
            for text,expr in c[1]: chunks.append(text if expr is None else str(await self.evaluate_compiled(self.compile(expr,syntax='native'),context)))
            result=''.join(chunks)
            if len(result)>MAX_RENDERED: raise ExpressionError('resource limit','Rendered template is too long')
            return result
        if c[0]=='expression':
            value=await self._eval(c[1],context)
            return value
        raise ExpressionError('internal','Invalid compiled expression')
    async def _eval(self,n,ctx):
        typ=n[0]
        if typ=='literal': return n[1]
        if typ=='name': return ctx.get(n[1], {'true':True,'false':False,'none':None}.get(n[1],Undefined))
        if typ=='list': return [await self._eval(x,ctx) for x in n[1]]
        if typ=='mapping': return {await self._eval(k,ctx):await self._eval(v,ctx) for k,v in n[1]}
        if typ=='unary':
            value=await self._eval(n[2],ctx); return (not self._bool(value)) if n[1]=='Not' else (-value if n[1]=='USub' else +value)
        if typ=='binary':
            a,b=await self._eval(n[2],ctx),await self._eval(n[3],ctx)
            try: return {'Add':lambda:a+b,'Sub':lambda:a-b,'Mult':lambda:a*b,'Div':lambda:a/b,'Mod':lambda:a%b,'FloorDiv':lambda:a//b}[n[1]]()
            except Exception: raise ExpressionError('type','Invalid arithmetic operands') from None
        if typ=='bool':
            if n[1]=='And':
                for x in n[2]:
                    v=await self._eval(x,ctx)
                    if not self._bool(v): return False
                return True
            for x in n[2]:
                if self._bool(await self._eval(x,ctx)): return True
            return False
        if typ=='compare':
            a,b=await self._eval(n[2],ctx),await self._eval(n[3],ctx)
            if a is Undefined or b is Undefined:return False
            try:
                if n[1]=='Eq': return a==b
                if n[1]=='NotEq': return a!=b
                if n[1]=='Gt': return a>b
                if n[1]=='GtE': return a>=b
                if n[1]=='Lt': return a<b
                if n[1]=='LtE': return a<=b
                if n[1]=='In': return a in b
                return a not in b
            except Exception: raise ExpressionError('type','Invalid comparison') from None
        if typ=='if': return await self._eval(n[2] if self._bool(await self._eval(n[1],ctx)) else n[3],ctx)
        if typ=='index':
            base,key=await self._eval(n[1],ctx),await self._eval(n[2],ctx)
            try:
                if isinstance(base,(dict,list,tuple,str)) and not (isinstance(base,dict) and str(key).startswith('_')): return base[key]
            except (KeyError,IndexError,TypeError): pass
            return Undefined
        if typ=='attribute':
            base=await self._eval(n[1],ctx)
            if isinstance(base,Snapshot): return {'entity_ref':base.entity_ref,'entity_id':base.entity_id,'state':base.state,'attributes':base.attributes,'availability':base.availability,'timestamp':base.timestamp}.get(n[2],Undefined)
            if isinstance(base,Mapping) and not n[2].startswith('_'): return base.get(n[2],Undefined)
            return Undefined
        if typ=='call': return await self._call(n[1],[await self._eval(x,ctx) for x in n[2]],ctx)
        raise ExpressionError('internal','Unknown AST node')
    def _bool(self,v):
        if v is Undefined or v is None or v is False:return False
        if isinstance(v,str): return v.lower() in ('true','on','yes','1')
        return bool(v)
    async def _call(self,name,args,ctx):
        if name in ('states','is_state','state_attr'):
            if not args or not isinstance(args[0],str): return Undefined if name!='is_state' else False
            snap=await self._state(args[0]);
            if name=='states': return snap.state if snap is not None else Undefined
            if name=='is_state': return snap is not None and len(args)>1 and snap.state==args[1]
            return snap.attributes.get(args[1],Undefined) if snap and len(args)>1 else Undefined
        if name in ('float','int','string','bool'):
            value=args[0] if args else Undefined; default=args[1] if len(args)>1 else (0.0 if name=='float' else 0 if name=='int' else '')
            try:
                if value is Undefined:return default
                if name=='float':return float(value)
                if name=='int':return int(float(value))
                if name=='string':return str(value)
                return self._bool(value)
            except (TypeError,ValueError): return default
        if name=='default': return args[1] if args and (args[0] is Undefined or args[0] is None or (len(args)>2 and args[2] and not args[0])) else (args[0] if args else Undefined)
        if name in ('lower','upper','trim'): return (str(args[0]) if args else '').lower() if name=='lower' else ((str(args[0]) if args else '').upper() if name=='upper' else (str(args[0]) if args else '').strip())
        if name=='replace': return str(args[0]).replace(str(args[1]),str(args[2])) if len(args)>2 else str(args[0])
        if name in ('length','count'): return len(args[0]) if args and isinstance(args[0],(str,list,dict,tuple)) else 0
        if name=='first': return args[0][0] if args and args[0] else Undefined
        if name=='last': return args[0][-1] if args and args[0] else Undefined
        if name=='join': return (str(args[0]) if len(args)<2 else str(args[1])).join(str(x) for x in (args[1] if len(args)>1 else args[0]))
        if name=='list': return list(args[0]) if args and isinstance(args[0],(list,tuple,dict,str)) else []
        if name in ('min','max'): return (min if name=='min' else max)(args[0]) if len(args)==1 and isinstance(args[0],(list,tuple)) else (min(args) if name=='min' else max(args))
        if name in ('round','abs'): return round(*args) if name=='round' else abs(args[0])
        if name=='now': return datetime.now(self.timezone)
        if name=='utcnow': return datetime.now(timezone.utc)
        if name=='today_at': return datetime.combine(datetime.now(self.timezone).date(),time.fromisoformat(str(args[0])),self.timezone)
        if name=='duration': return timedelta(**{str(k):v for k,v in (args[0].items() if args and isinstance(args[0],dict) else [])})
        if name=='as_timestamp':
            value=args[0] if args else Undefined
            if isinstance(value,datetime): return value.timestamp()
            try:return float(value)
            except (TypeError,ValueError):return Undefined
        if name=='as_datetime':
            value=args[0] if args else Undefined
            try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
            except ValueError:return Undefined
        if name=='as_local':
            value=args[0] if args else Undefined
            return value.astimezone(self.timezone) if isinstance(value,datetime) else Undefined
        if name in ('startswith','endswith'): return str(args[0]).startswith(str(args[1])) if name=='startswith' else str(args[0]).endswith(str(args[1]))
        raise ExpressionError('unknown function',f'Unknown function: {name}')
    async def _state(self,entity_id):
        if self.resolver: return await self.resolver(entity_id)
        async with db.acquire() as conn:
            row=await conn.fetchrow('SELECT id,entity_id,state,attributes,available,last_updated FROM entities WHERE entity_id=$1 AND enabled',entity_id)
        if not row:return None
        return Snapshot(int(row['id']),row['entity_id'],row['state'],row['attributes'] or {},bool(row['available']),row['last_updated'])
