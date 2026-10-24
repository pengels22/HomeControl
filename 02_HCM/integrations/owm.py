"""OpenWeatherMap provider with encrypted API-key access."""
import asyncio
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .weather import WeatherState,ForecastEntry,ForecastRequest,normalize_condition,record_poll,forecast_response

class OWMProvider(Provider):
    info=ProviderInfo('openweathermap','OpenWeatherMap',capabilities={'weather':True},description='OpenWeatherMap current weather and forecast',setup_type='api_key',supports_multiple=True,config_schema={'type':'object','properties':{'latitude':{'type':'number'},'longitude':{'type':'number'},'units':{'type':'string','enum':['standard','metric','imperial']},'interval':{'type':'integer','minimum':60}},'required':['latitude','longitude'],'additionalProperties':False},config_flow={'type':'api_key','credential_kinds':['api_key'],'fields':[{'name':'latitude','type':'number','required':True},{'name':'longitude','type':'number','required':True},{'name':'units','type':'select','options':['metric','imperial']}]})
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(); self.device=None; self.entity=None; self.last=None; self.updates=0; self.task=None
    async def setup(self,context):
        self.context=context; self.device=await context.device('weather','Weather',available=False); self.entity=await context.entity('weather','weather.current',self.device,'Weather')
        await context.service('weather','get_forecast',ForecastRequest,self._get_forecast,target_required=True,target_domains=('weather',))
    async def _get_forecast(self,args,target):
        if self.last is None: return {'status':'backend_unavailable'}
        return forecast_response(self.last,args.type)
    async def poll(self):
        key=await self.context.credential(); cfg=self.context.config; params={'lat':cfg['latitude'],'lon':cfg['longitude'],'appid':key,'units':cfg.get('units','imperial')}; data,_=await self.client.json('GET','https://api.openweathermap.org/data/2.5/weather',params=params); forecast_data,_=await self.client.json('GET','https://api.openweathermap.org/data/2.5/forecast',params=params)
        main=data.get('main',{}); wind=data.get('wind',{}); forecast=[]
        for item in forecast_data.get('list',[]):
            m=item.get('main',{}); w=item.get('wind',{}); rain=item.get('rain',{}); forecast.append(ForecastEntry(start=item.get('dt_txt'),condition=normalize_condition((item.get('weather') or [{}])[0].get('main')),temperature=m.get('temp'),apparent_temperature=m.get('feels_like'),humidity=m.get('humidity'),pressure=m.get('pressure'),wind_speed=w.get('speed'),wind_direction=str(w.get('deg')) if w.get('deg') is not None else None,precipitation_probability=item.get('pop'),precipitation=rain.get('3h'),cloud_coverage=(item.get('clouds') or {}).get('all')).as_dict())
        state=WeatherState(condition=normalize_condition((data.get('weather') or [{}])[0].get('main')),temperature=main.get('temp'),apparent_temperature=main.get('feels_like'),humidity=main.get('humidity'),pressure=main.get('pressure'),wind_speed=wind.get('speed'),wind_direction=str(wind.get('deg')) if wind.get('deg') is not None else None,forecast=forecast,provider='openweathermap')
        await self.context.state(self.entity,state.as_dict(),attributes={'provider':'openweathermap'}); await self.context.device('weather','Weather',available=True); self.last=state; self.updates+=1; await record_poll(self.context,True)
    async def start(self): await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',900))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def reload(self):
        await self.stop(); self.client=ProviderHTTP(); await self.start()
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'authenticated':self.last is not None})

if 'openweathermap' not in provider_factory.types: provider_factory.register_type('openweathermap',OWMProvider.info,lambda context:OWMProvider())
