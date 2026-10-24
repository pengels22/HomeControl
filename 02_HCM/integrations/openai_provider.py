"""OpenAI service provider. It cannot control devices or outputs."""
from pydantic import BaseModel,ConfigDict,Field
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP

class GenerateText(BaseModel):
    model_config=ConfigDict(extra='forbid'); prompt:str=Field(min_length=1,max_length=12000); system:str|None=Field(default=None,max_length=4000); model:str|None=None; max_tokens:int=Field(default=512,ge=1,le=4096)
class OpenAIProvider(Provider):
    info=ProviderInfo('openai','OpenAI',capabilities={'services':True},description='OpenAI text generation service',setup_type='api_key',supports_multiple=True,config_schema={'type':'object','properties':{'model':{'type':'string','enum':['gpt-4o-mini','gpt-4.1-mini']},'timeout':{'type':'integer','minimum':1,'maximum':60}},'additionalProperties':False},config_flow={'type':'api_key','credential_kinds':['api_key'],'fields':[{'name':'model','type':'select','options':['gpt-4o-mini','gpt-4.1-mini']},{'name':'timeout','type':'integer'}]})
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(timeout=30); self.requests=0; self.successes=0
    async def setup(self,context): self.context=context; await context.service('openai','generate_text',GenerateText,self.generate)
    async def generate(self,args,target=None):
        key=await self.context.credential(); cfg=self.context.config; headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'}; messages=([{'role':'system','content':args.system}] if args.system else [])+[{'role':'user','content':args.prompt}]
        data,_=await self.client.json('POST','https://api.openai.com/v1/chat/completions',headers=headers,json_body={'model':args.model or cfg.get('model','gpt-4o-mini'),'messages':messages,'max_tokens':args.max_tokens}); self.requests+=1; self.successes+=1
        return {'text':((data.get('choices') or [{}])[0].get('message') or {}).get('content',''),'model':data.get('model')}
    async def start(self): pass
    async def stop(self): await self.client.close()
    async def health_check(self): return bool(self.context and self.context.credential_ref)
    async def diagnostics(self): return Diagnostics(counters={'requests':self.requests,'successes':self.successes},checks={'credential_present':bool(self.context and self.context.credential_ref)})

if 'openai' not in provider_factory.types: provider_factory.register_type('openai',OpenAIProvider.info,lambda context:OpenAIProvider())
