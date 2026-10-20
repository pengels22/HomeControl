"""National Weather Service provider; no credential required."""
import asyncio
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .weather import WeatherState

class NWSProvider(Provider):
    info=ProviderInfo('nws','National Weather Service',capabilities={'weather':True,'alerts':True},description='US National Weather Service forecasts and alerts',setup_type='simple',supports_multiple=True,config_schema={'type':'object','properties':{'latitude':{'type':'number'},'longitude':{'type':'number'},'interval':{'type':'integer','minimum':60}},'required':['latitude','longitude'],'additionalProperties':False},config_flow={'type':'simple','fields':[{'name':'latitude','type':'number','required':True},{'name':'longitude','type':'number','required':True},{'name':'interval','type':'duration'}]})
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(); self.task=None; self.points=None; self.last=None; self.updates=0; self.alert_ids=set(); self.fail=False
    async def setup(self,context):
        self.context=context; self.device=await context.device('weather','Weather',available=False); self.entity=await context.entity('weather','weather.current',self.device,'Weather'); self.temperature=await context.entity('temperature','temperature.outdoor',self.device,'Outdoor Temperature',unit='°F')
    async def poll(self):
        lat=self.context.config.get('latitude'); lon=self.context.config.get('longitude')
        if lat is None or lon is None: raise ValueError('Latitude and longitude are required')
        if not self.points: self.points,_=await self.client.json('GET',f'https://api.weather.gov/points/{lat},{lon}',headers={'User-Agent':'HomeControl/1.0'})
        forecast,_=await self.client.json('GET',self.points['properties']['forecast'],headers={'User-Agent':'HomeControl/1.0'})
        period=(forecast.get('properties',{}).get('periods') or [{}])[0]; state=WeatherState(condition=period.get('shortForecast'),temperature=period.get('temperature'),wind_speed=period.get('windSpeed'),wind_direction=period.get('windDirection'),forecast=forecast.get('properties',{}).get('periods',[])[:7],provider='nws')
        await self.context.state(self.entity,state.as_dict(),attributes={'provider':'nws'}); await self.context.state(self.temperature,state.temperature,attributes={'unit':'°F'}); await self.context.device('weather','Weather',available=True); self.last=state; self.updates+=1
    async def start(self):
        await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',900))))
            try: await self.poll()
            except Exception: pass
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def reload(self): self.points=None; await self.stop(); self.client=ProviderHTTP(); await self.start()
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'forecast_resolved':self.points is not None})

if 'nws' not in provider_factory.types: provider_factory.register_type('nws',NWSProvider.info,lambda context:NWSProvider())
