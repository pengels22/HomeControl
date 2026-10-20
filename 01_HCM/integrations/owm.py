"""OpenWeatherMap provider with encrypted API-key access."""
import asyncio
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .weather import WeatherState

class OWMProvider(Provider):
    info=ProviderInfo('openweathermap','OpenWeatherMap',capabilities={'weather':True},description='OpenWeatherMap current weather and forecast',setup_type='api_key',supports_multiple=True,config_schema={'type':'object','properties':{'latitude':{'type':'number'},'longitude':{'type':'number'},'units':{'type':'string','enum':['standard','metric','imperial']},'interval':{'type':'integer','minimum':60}},'required':['latitude','longitude'],'additionalProperties':False},config_flow={'type':'api_key','credential_kinds':['api_key'],'fields':[{'name':'latitude','type':'number','required':True},{'name':'longitude','type':'number','required':True},{'name':'units','type':'select','options':['metric','imperial']}]})
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(); self.device=None; self.entity=None; self.last=None; self.updates=0; self.task=None
    async def setup(self,context): self.context=context; self.device=await context.device('weather','Weather',available=False); self.entity=await context.entity('weather','weather.current',self.device,'Weather')
    async def poll(self):
        key=await self.context.credential(); cfg=self.context.config; data,_=await self.client.json('GET','https://api.openweathermap.org/data/2.5/weather',params={'lat':cfg['latitude'],'lon':cfg['longitude'],'appid':key,'units':cfg.get('units','imperial')})
        main=data.get('main',{}); wind=data.get('wind',{}); state=WeatherState(condition=(data.get('weather') or [{}])[0].get('main'),temperature=main.get('temp'),apparent_temperature=main.get('feels_like'),humidity=main.get('humidity'),pressure=main.get('pressure'),wind_speed=wind.get('speed'),wind_direction=str(wind.get('deg')) if wind.get('deg') is not None else None,provider='openweathermap')
        await self.context.state(self.entity,state.as_dict(),attributes={'provider':'openweathermap'}); await self.context.device('weather','Weather',available=True); self.last=state; self.updates+=1
    async def start(self): await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',900))))
            try: await self.poll()
            except Exception: pass
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def reload(self):
        await self.stop(); self.client=ProviderHTTP(); await self.start()
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'authenticated':self.last is not None})

if 'openweathermap' not in provider_factory.types: provider_factory.register_type('openweathermap',OWMProvider.info,lambda context:OWMProvider())
