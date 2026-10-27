(function(){
'use strict';
const state={connected:false,entities:new Map(),busy:new Set()};
const API=window.HA_MONITOR={
 get connected(){return state.connected},
 get(id){return state.entities.get(id)},
 async refresh(){
  try{
   const resp=await fetch('/api/entities',{cache:'no-store'});
   if(!resp.ok)throw new Error('HA '+resp.status);
   const values=await resp.json();
   state.entities=new Map(values.map(v=>[v.entity_id,v]));
   state.connected=true;
  }catch(e){state.connected=false;}
  window.dispatchEvent(new Event('ha-state-update'));
 },
 async command(entity_id,command,extra={}){
  if(!state.connected || state.busy.has(entity_id))throw Error('Backend offline or busy');
  state.busy.add(entity_id);
  try{
   const resp=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({entity_id,command,...extra})});
   const data=await resp.json();
   if(!resp.ok)throw Error(data.error||'Command failed');
   await API.refresh();
   return data;
  }finally{state.busy.delete(entity_id)}
 },
 async toggle(id){
  const v=state.entities.get(id);
  if(!v || !['on','off'].includes(v.state))throw Error('Entity unavailable');
  return API.command(id,v.state==='on'?'turn_off':'turn_on');
 }
};
API.refresh();setInterval(()=>API.refresh(),2000);
})();
