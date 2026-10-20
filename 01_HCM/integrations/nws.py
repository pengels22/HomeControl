"""National Weather Service provider; no credential required."""
import asyncio
from .provider import Provider,ProviderInfo,Diagnostics
from .factory import provider_factory
from .http import ProviderHTTP
from .weather import WeatherState,ForecastEntry,normalize_condition,record_poll

class NWSProvider(Provider):
    info=ProviderInfo('nws','National Weather Service',capabilities={'weather':True,'alerts':True},description='US National Weather Service forecasts and alerts',setup_type='simple',supports_multiple=True,config_schema={'type':'object','properties':{'latitude':{'type':'number'},'longitude':{'type':'number'},'interval':{'type':'integer','minimum':60}},'required':['latitude','longitude'],'additionalProperties':False},config_flow={'type':'simple','fields':[{'name':'latitude','type':'number','required':True},{'name':'longitude','type':'number','required':True},{'name':'interval','type':'duration'}]})
    def __init__(self,client=None): self.context=None; self.client=client or ProviderHTTP(); self.task=None; self.points=None; self.last=None; self.updates=0; self.alert_ids={}; self.fail=False
    async def setup(self,context):
        self.context=context; self.device=await context.device('weather','Weather',available=False); self.entity=await context.entity('current','weather.current',self.device,'Weather'); self.temperature=await context.entity('temperature','temperature.outdoor',self.device,'Outdoor Temperature',unit='F'); self.alert_count=await context.entity('alert_count','sensor.weather_alert_count',self.device,'Active Weather Alerts'); self.alert_active=await context.entity('alert_active','binary_sensor.weather_alert_active',self.device,'Weather Alert Active')
    async def poll(self):
        lat=self.context.config.get('latitude'); lon=self.context.config.get('longitude')
        if lat is None or lon is None: raise ValueError('Latitude and longitude are required')
        if not self.points: self.points,_=await self.client.json('GET',f'https://api.weather.gov/points/{lat},{lon}',headers={'User-Agent':'HomeControl/1.0'})
        forecast,_=await self.client.json('GET',self.points['properties']['forecast'],headers={'User-Agent':'HomeControl/1.0'})
        period=(forecast.get('properties',{}).get('periods') or [{}])[0]; periods=forecast.get('properties',{}).get('periods',[])[:7]; normalized=[ForecastEntry(start=p.get('startTime'),end=p.get('endTime'),condition=normalize_condition(p.get('shortForecast')),temperature=p.get('temperature'),wind_speed=p.get('windSpeed'),wind_direction=p.get('windDirection'),precipitation_probability=(p.get('probabilityOfPrecipitation') or {}).get('value')).as_dict() for p in periods]; state=WeatherState(condition=normalize_condition(period.get('shortForecast')),temperature=period.get('temperature'),wind_speed=period.get('windSpeed'),wind_direction=period.get('windDirection'),forecast=normalized,provider='nws')
        await self.context.state(self.entity,state.as_dict(),attributes={'provider':'nws'}); await self.context.state(self.temperature,state.temperature,attributes={'unit':'F'}); await self.context.device('weather','Weather',available=True); self.last=state; self.updates+=1
        alerts,_=await self.client.json('GET',f"https://api.weather.gov/alerts/active?point={lat},{lon}",headers={'User-Agent':'HomeControl/1.0'}); active={f.get('id'):f.get('properties',{}) for f in alerts.get('features',[]) if f.get('id')}
        for alert_id,props in active.items():
            version=repr({k:props.get(k) for k in ('event','severity','urgency','certainty','headline','description','instruction','effective','expires')})
            if alert_id not in self.alert_ids: await self.context.emit('nws.alert_started',self._alert(alert_id,props))
            elif self.alert_ids[alert_id]!=version: await self.context.emit('nws.alert_updated',self._alert(alert_id,props))
            self.alert_ids[alert_id]=version
        for alert_id in set(self.alert_ids)-set(active): await self.context.emit('nws.alert_ended',{'alert_id':alert_id}); self.alert_ids.pop(alert_id,None)
        await self.context.state(self.alert_count,len(active)); await self.context.state(self.alert_active,bool(active)); await record_poll(self.context,True)

    def _alert(self,alert_id,props):
        return {'alert_id':alert_id,**{k:props.get(k) for k in ('event','severity','urgency','certainty','effective','onset','expires','headline','description','instruction','areaDesc')}}
    async def start(self):
        await self.poll(); self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            await asyncio.sleep(max(60,int(self.context.config.get('interval',900))))
            try: await self.poll()
            except Exception as exc: await record_poll(self.context,False,type(exc).__name__)
    async def stop(self):
        if self.task: self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close(); self.task=None
    async def reload(self): self.points=None; await self.stop(); self.client=ProviderHTTP(); await self.start()
    async def health_check(self): return self.last is not None
    async def diagnostics(self): return Diagnostics(counters={'updates':self.updates},checks={'forecast_resolved':self.points is not None})

if 'nws' not in provider_factory.types: provider_factory.register_type('nws',NWSProvider.info,lambda context:NWSProvider())
