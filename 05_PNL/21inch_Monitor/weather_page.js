(function(){
 'use strict';

 const button=document.querySelector('[data-page="weather"]');
 const central=document.querySelector('.central');
 const scene=document.querySelector('.static-scene');
 const title=document.getElementById('page-title');
 if(!button)return;

 const whole=value=>{const n=Number(value);return Number.isFinite(n)?String(Math.round(n)):String(value??'—')};
 const conditionIcon={clear:'☀',sunny:'☀',partlycloudy:'⛅',cloudy:'☁',rainy:'☂',pouring:'☂',snowy:'❄',fog:'≋',windy:'〰'};
 const radarLocation={lat:42.87332621222384,lon:-85.60950279235841};
 let radarCache=null;
 let radarFetchedAt=0;

 function weatherEntity(){
   const get=id=>window.HA_MONITOR?.get(id);
   const preferred=get('weather.forecast_home_2');
   return preferred&&!['unknown','unavailable'].includes(preferred.state)?preferred:get('weather.openweathermap')||get('weather.kgrr');
 }

 function tilePosition(lat,lon,zoom){
   const n=2**zoom;
   const x=(lon+180)/360*n;
   const y=(1-Math.log(Math.tan(lat*Math.PI/180)+1/Math.cos(lat*Math.PI/180))/Math.PI)/2*n;
   return {x:Math.floor(x),y:Math.floor(y)};
 }

 function tileUrl(host,path,zoom,x,y){
   return host+path+'/256/'+zoom+'/'+x+'/'+y+'/2/1_1.png';
 }

 function radarFrame(data){
   const nowcast=data?.radar?.nowcast||[];
   const past=data?.radar?.past||[];
   return {frame:(nowcast.length?nowcast[nowcast.length-1]:past[past.length-1]),forecast:Boolean(nowcast.length)};
 }

 function radarMarkup(data){
   const selected=radarFrame(data);
   const frame=selected.frame;
   const host=data?.host;
   if(!frame||!host){
     return '<section class="page-panel radar-panel"><div class="panel-heading"><h2>Weather radar</h2></div><p class="panel-note">Radar is temporarily unavailable.</p></section>';
   }

   return '<section class="page-panel radar-panel"><div class="panel-heading"><h2>Weather radar</h2><span class="state-badge live">'+(selected.forecast?'Forecast':'Observed radar')+'</span></div><div class="radar-map" data-radar-host="'+host+'" data-radar-path="'+frame.path+'"><div class="radar-tile-layer"></div><div class="radar-location" aria-label="Home location">⌖</div><div class="radar-controls"><button type="button" data-radar-zoom="in" aria-label="Zoom in">+</button><button type="button" data-radar-zoom="out" aria-label="Zoom out">−</button><button type="button" data-radar-zoom="reset" aria-label="Reset radar view">⌂</button></div><div class="radar-help">Drag to pan · pinch or use + / − to zoom</div></div><div class="radar-attribution">Map © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> · Radar by <a href="https://www.rainviewer.com/" target="_blank" rel="noreferrer">RainViewer</a></div></section>';
 }

 function bindRadar(panel){
   const map=panel?.querySelector('.radar-map');
   const layer=map?.querySelector('.radar-tile-layer');
   if(!map||!layer)return;
   const host=map.dataset.radarHost;
   const path=map.dataset.radarPath;
   const state={zoom:7,offsetX:0,offsetY:0,pointers:new Map(),startX:0,startY:0,startOffsetX:0,startOffsetY:0};
   const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
   const render=()=>{
     const center=tilePosition(radarLocation.lat,radarLocation.lon,state.zoom);
     const n=2**state.zoom;
     const size=1280;
     let html='';
     for(let dy=-2;dy<=2;dy++){
       for(let dx=-2;dx<=2;dx++){
         const x=((center.x+dx)%n+n)%n;
         const y=clamp(center.y+dy,0,n-1);
         const left=(dx+2)*256;
         const top=(dy+2)*256;
         html+='<img class="radar-tile" style="left:'+left+'px;top:'+top+'px" src="https://tile.openstreetmap.org/'+state.zoom+'/'+x+'/'+y+'.png" alt="">';
         html+='<img class="radar-tile radar-rain-tile" style="left:'+left+'px;top:'+top+'px" src="'+tileUrl(host,path,state.zoom,x,y)+'" alt="">';
       }
     }
     layer.style.width=size+'px';
     layer.style.height=size+'px';
     layer.style.transform='translate(calc(-50% + '+state.offsetX+'px),calc(-50% + '+state.offsetY+'px))';
     layer.innerHTML=html;
   };
   const reset=()=>{state.zoom=7;state.offsetX=0;state.offsetY=0;render()};
   panel.querySelectorAll('[data-radar-zoom]').forEach(control=>control.addEventListener('click',()=>{
     const action=control.dataset.radarZoom;
     if(action==='reset')return reset();
     state.zoom=clamp(state.zoom+(action==='in'?1:-1),3,7);
     state.offsetX=0;state.offsetY=0;render();
   }));
   map.addEventListener('pointerdown',event=>{
     map.setPointerCapture(event.pointerId);
     state.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
     if(state.pointers.size===1){state.startX=event.clientX;state.startY=event.clientY;state.startOffsetX=state.offsetX;state.startOffsetY=state.offsetY;}
   });
   map.addEventListener('pointermove',event=>{
     if(!state.pointers.has(event.pointerId)||state.pointers.size!==1)return;
     state.offsetX=state.startOffsetX+event.clientX-state.startX;
     state.offsetY=state.startOffsetY+event.clientY-state.startY;
     layer.style.transform='translate(calc(-50% + '+state.offsetX+'px),calc(-50% + '+state.offsetY+'px))';
   });
   const endPointer=event=>state.pointers.delete(event.pointerId);
   map.addEventListener('pointerup',endPointer);
   map.addEventListener('pointercancel',endPointer);
   map.addEventListener('wheel',event=>{event.preventDefault();state.zoom=clamp(state.zoom+(event.deltaY<0?1:-1),3,7);state.offsetX=0;state.offsetY=0;render()},{passive:false});
   render();
 }

 async function loadRadar(){
   if(radarCache&&Date.now()-radarFetchedAt<300000)return radarCache;
   const response=await fetch('/api/radar',{cache:'no-store'});
   if(!response.ok)throw new Error('Radar request failed');
   radarCache=await response.json();
   radarFetchedAt=Date.now();
   return radarCache;
 }

 async function renderWeather(){
   scene.hidden=true;
   const old=document.getElementById('page-content');
   if(old)old.remove();
   title.textContent='Weather';
   const item=weatherEntity();
   const attrs=item?.attributes||{};
   const condition=String(item?.state||'unavailable').replaceAll('_',' ');
   const icon=conditionIcon[item?.state]||'☁';
   const content=document.createElement('div');
   content.id='page-content';
   const temp=whole(attrs.temperature);
   const outdoor=window.HA_MONITOR?.get('sensor.outside_temp_temperature');
   const feels=whole(outdoor&&!['unknown','unavailable'].includes(outdoor.state)?outdoor.state:attrs.apparent_temperature);
   const humidity=whole(attrs.humidity);
   const wind=whole(attrs.wind_speed);
   const uv=whole(attrs.uv_index);
   content.innerHTML='<style>'+[
     '.weather-grid{height:100%;grid-template-columns:minmax(260px,.8fr) minmax(0,1.5fr)}',
     '.weather-summary{min-height:0}',
     '.radar-panel{min-height:0;display:flex;flex-direction:column}',
     '.radar-map{position:relative;flex:1;min-height:300px;overflow:hidden;border-radius:10px;background:#1b2a34}',
     '.radar-tile-layer{position:absolute;width:768px;height:768px;left:50%;top:50%;transform:translate(-50%,-50%)}',
     '.radar-tile{position:absolute;width:256px;height:256px;display:block}',
     '.radar-rain-tile{opacity:.75}',
     '.radar-location{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);color:#fff;background:#157ec1;border:2px solid #fff;border-radius:50%;width:25px;height:25px;line-height:20px;text-align:center;font-size:22px;text-shadow:0 1px 2px #000;box-shadow:0 1px 8px #0008}',
     '.radar-controls{position:absolute;right:10px;top:10px;display:flex;gap:6px;z-index:2}',
     '.radar-controls button{width:42px;height:42px;padding:0;border:1px solid #5f7b8d;border-radius:8px;background:#183246;color:#fff;font-size:27px;line-height:1;touch-action:manipulation}',
     '.radar-controls button:active{background:var(--accent);transform:scale(.96)}',
     '.radar-help{position:absolute;left:10px;bottom:8px;z-index:2;padding:4px 7px;border-radius:5px;background:#07121dcc;color:#d6e3eb;font-size:11px;pointer-events:none}',
     '.radar-attribution{font-size:11px;color:var(--muted);margin-top:7px}',
     '.radar-attribution a{color:var(--accent)}',
     '@media(max-width:900px){.weather-grid{grid-template-columns:1fr}.radar-map{min-height:260px}}'
   ].join('')+'</style><div class="page-grid weather-grid"><section class="page-panel weather-summary"><div class="panel-heading"><h2>'+icon+' Weather</h2><span class="state-badge '+(item?'live':'unavailable')+'">'+(item?'Live conditions':'Unavailable')+'</span></div><div class="big-reading">'+temp+'°F</div><p class="panel-note" style="font-size:18px;text-transform:capitalize">'+condition+'</p><div class="reading-list"><div><b>Feels like</b><span>'+feels+'°F</span></div><div><b>Humidity</b><span>'+humidity+'%</span></div><div><b>Wind</b><span>'+wind+' mph</span></div><div><b>UV index</b><span>'+uv+'</span></div></div><p class="panel-note" style="margin-top:18px">'+(attrs.friendly_name||'Home weather')+'</p></section><section class="page-panel radar-panel"><div class="panel-heading"><h2>Weather radar</h2><span class="state-badge">Loading…</span></div><div class="radar-map" style="display:grid;place-items:center"><span class="panel-note">Loading radar…</span></div></section></div>';
   central.append(content);
   try{
     const radar=await loadRadar();
     const panel=content.querySelector('.radar-panel');
     if(panel){panel.outerHTML=radarMarkup(radar);bindRadar(content.querySelector('.radar-panel'))}
   }catch(error){
     const panel=content.querySelector('.radar-panel');
     if(panel)panel.outerHTML=radarMarkup(null);
   }
 }

 button.onclick=()=>{
   document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x===button));
   renderWeather();
 };
 window.addEventListener('ha-state-update',()=>{if(button.classList.contains('active'))renderWeather()});
})();
