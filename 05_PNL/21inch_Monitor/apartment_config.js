// Editable sketch-derived model data. Coordinates are approximate and intentionally
// not presented as a measured architectural survey.
window.APARTMENT_CONFIG = {
  units: 'arbitrary',
  rooms: [
    {id:'bedroom', name:'Bedroom', x:-7.0, z:-3.0, w:4.8, d:4.0, finish:'wood', color:'#354b5c', lights:[
      ['Fan','switch.bedroom_fan_switch'],['Wreath','switch.barbecue_lights_switch'],['Hubby Glow','light.hubby_glow_light'],['Wifey Glow','light.wifey_glow_light'],['Under Bed','light.bed_underglow_light'],['Vines','switch.bedroom_vines_switch'],['Lamps','light.bedroom_lamp_light'],['Head White','light.headboard_white_light'],['Bedroom Over','switch.bedroom_light'],['Bedroom TV','switch.bedroom_tv_switch']],
      furniture:[['Bed',0,0,2.7,2.0,.45],['Nightstand',-1.75,-.65,.55,.65,.5],['Nightstand',1.75,-.65,.55,.65,.5]]},
    {id:'office', name:'Office', x:-7.0, z:2.0, w:4.8, d:3.8, finish:'laminate', color:'#384f60', lights:[
      ['Desk Lights','switch.modem_power_switch'],['Office Lights','switch.office_lights_switch_2'],['Printer Lights','switch.printer_lights_switch'],['Workbench','switch.workbench_switch'],['TV Schedule','automation.bedroom_tv_off_schedule'],['Desk Over','light.office_desk_lights'],['Compressor','switch.air_compressor_switch'],['Laser Fan','light.office_laser_fan'],['Bathroom Toe','light.bathroom_toe']],
      furniture:[['Desk',-.8,-.9,2.6,.65,.8],['Cabinet',1.45,.65,.65,1.3,.9],['Chair',-.8,.25,.75,.75,.75]]},
    {id:'bathroom', name:'Bathroom', x:-3.35, z:-1.7, w:2.5, d:2.2, finish:'tile', color:'#3c515e', lights:[['Bathroom','light.bathroom_toe']], furniture:[['Sink',-.65,0,.7,.5,.8],['Toilet',.65,.1,.55,.75,.65],['Shower',0,-.75,1.0,.45,1.8]]},
    {id:'hallway', name:'Hallway', x:-3.35, z:1.0, w:2.5, d:2.2, finish:'laminate', color:'#3d5361', lights:[['Hallway','switch.hallway_light']], furniture:[['Closet',0,0,1.9,.5,1.8]]},
    {id:'living', name:'Living Room', x:.4, z:-1.2, w:5.0, d:4.9, finish:'wood', color:'#405666', lights:[
      ['Lamp','switch.lamp_switch'],['Stove','light.cabinets_lights_light'],["TV LED's",'light.tv_leds_light'],['Living Room','switch.office_lights_switch'],['Jack And Sally','switch.scenic_1_switch'],['Desk Led','light.desk_leds_light'],['Seasonal','switch.seasonal_switches'],['Laundry','switch.laundry_room'],['Living Room Glow','light.living_room_glow'],['Records','light.living_room_records'],['Living Room Glow All','light.living_room_glow_all']],
      furniture:[['Couch',-.8,-.55,2.8,.8,.75],['Coffee Table',-.6,.75,1.7,.8,.4],['TV',1.85,.2,.35,2.0,1.4],['Media Console',1.85,1.15,.65,2.4,.65]]},
    {id:'kitchen', name:'Kitchen / Dining', x:.4, z:2.55, w:5.0, d:2.6, finish:'tile', color:'#4a5b61', lights:[['Kitchen','light.cabinets_lights_light'],['Dining','switch.kitchen_light']], furniture:[['Counter',0,-.85,4.3,.45,1.0],['Island',.1,.15,1.4,1.0,.9],['Fridge',1.95,.75,.6,.7,1.9],['Dining Table',-.8,1.0,1.7,.8,.75]]},
    {id:'patio', name:'Patio', x:6.0, z:-2.8, w:3.1, d:4.0, finish:'exterior', color:'#2f4d50', exterior:true, lights:[['Patio','light.patio_light']], furniture:[['Outdoor Table',0,0,1.5,1.1,.65],['Chair',-.95,0,.5,.6,.65],['Chair',.95,0,.5,.6,.65]]},
    {id:'laundry', name:'Laundry', x:6.0, z:1.5, w:3.1, d:2.7, finish:'tile', color:'#3d535c', lights:[['Laundry','switch.laundry_room']], furniture:[['Washer',-.75,0,.75,.75,.9],['Dryer',.75,0,.75,.75,.9]]}
  ]
};
