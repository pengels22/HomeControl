/* Approved trace coordinate space: viewBox 110 130 1250 720.
   Room touch areas and illumination are overlays ONLY; never change approved_trace.svg.
   Entry is OUTSIDE apartment and UI panels are NOT rooms. */
window.STATIC_APARTMENT={
 viewBox:'110 130 1250 720',
 rooms:[
 {id:'bedroom',name:'Bedroom',polygon:'185,215 430,215 430,473 185,473',sensors:[{entity:'binary_sensor.bedroom_window_opening',type:'door'},{entity:'binary_sensor.wifey_motion',type:'motion'},{entity:'binary_sensor.hubby_motion',type:'motion'}],lights:[['Headboard','light.headboard_white_light'],['Lamps','light.bedroom_lamp_light'],['Hubby Underglow','light.hubby_glow_light'],['Wifey Underglow','light.wifey_glow_light'],['Under Bed Underglow','light.bed_underglow_light'],['Bedroom Over','switch.bedroom_light'],['Fan','switch.bedroom_fan_switch'],['Bedroom TV','switch.bedroom_tv_switch'],['TV Schedule','automation.bedroom_tv_off_schedule'],['Vine Lights','switch.bedroom_vines_switch'],['Wreath','switch.barbecue_lights_switch']],zones:[['bedroom-over',306,344,109,104,'#ffd36a'],['bedroom-lamp-a',244,369,51,43,'#ffe29a'],['bedroom-lamp-b',365,368,52,43,'#ffe29a']]},
 {id:'bathroom',name:'Bathroom',polygon:'434,218 541,218 541,470 434,470',lights:[['Bathroom Toe','light.bathroom_toe']],zones:[['bathroom-over',487,345,48,100,'#e3f4ff']]},
 {id:'office',name:'Office',polygon:'186,479 374,479 374,705 186,705',sensors:[{entity:'binary_sensor.office_window_opening',type:'door'},{entity:'binary_sensor.hubby_office_motion',type:'motion'}],lights:[['Desk Lights','switch.modem_power_switch'],['Office Lights','switch.office_lights_switch_2'],['Printer Lights','switch.printer_lights_switch'],['Workbench','switch.workbench_switch']],zones:[['office-over',274,588,86,92,'#b9dcff'],['office-desk',250,553,49,51,'#ffd36a']]},
 {id:'closet',name:'Closet',polygon:'385,560 418,560 418,701 385,701',lights:[],zones:[]},
 {id:'big-pantry',name:'Big Pantry',polygon:'430,560 454,560 454,707 430,707',lights:[],zones:[]},
 {id:'hallway',name:'Hallway',polygon:'390,480 545,480 545,574 605,574 605,705 467,705 467,556 390,556',sensors:[{entity:'binary_sensor.inside_motion_occupancy',type:'motion'},{entity:'binary_sensor.ewelink_snzb_03p_motion',type:'motion'},{entity:'binary_sensor.front_door_sensor_opening',type:'door'}],lights:[['Hallway','preview.hallway.over']],zones:[['hallway-over',529,537,88,59,'#fff0ba']]},
 {id:'living',name:'Living Room',polygon:'550,218 870,218 870,579 610,579 610,475 550,475',sensors:[{entity:'binary_sensor.patio_door_opening_2',type:'door'},{entity:'binary_sensor.living_room_motion_occupancy',type:'motion'},{entity:'binary_sensor.living_room_motion_motion_2',type:'motion'}],lights:[['Lamp','switch.lamp_switch'],['Living Room','switch.office_lights_switch'],['Records','light.living_room_records']],zones:[['living-over',733,378,139,149,'#ffd36a'],['living-lamp',615,383,65,66,'#ffe29a'],['living-tv',826,349,42,76,'#80d7ff']]},
 {id:'kitchen',name:'Kitchen / Dining',polygon:'614,635 867,635 867,766 614,766',sensors:[{entity:'binary_sensor.kitchen_motion_occupancy',type:'motion'},{entity:'binary_sensor.kitchen_motion_motion_2',type:'motion'}],lights:[['Kitchen','light.cabinets_lights_light']],zones:[['kitchen-over',743,696,122,62,'#fff0ba'],['kitchen-dining',798,688,59,61,'#ffd36a']]},
 {id:'laundry',name:'Laundry',polygon:'883,591 1013,591 1013,761 883,761',sensors:[{entity:'binary_sensor.laundry_door',type:'door'}],lights:[['Laundry','switch.laundry_room']],zones:[['laundry-over',950,679,57,73,'#fff0ba']]},
 {id:'patio',name:'Patio',polygon:'888,222 997,222 997,571 888,571',lights:[['Patio','preview.patio.over']],zones:[['patio-over',950,407,49,134,'#a6d5ff']]}
 ],
 threeDRooms:[
  {id:'bedroom',anchor:[234.66,136.25],polygon:'85,60 300,125 290,280 155,245'},
  {id:'bathroom',anchor:[390.74,160.97],polygon:'305,90 420,150 390,270 305,220'},
  {id:'office',anchor:[123.28,226.56],polygon:'30,235 190,285 245,390 100,350'},
  {id:'living',anchor:[559.55,249.28],polygon:'410,125 750,195 740,350 470,315 400,270'},
  {id:'kitchen',anchor:[457.4,374.3],polygon:'320,320 480,325 540,410 400,450'},
  {id:'laundry',anchor:[617.13,430.25],polygon:'600,360 745,415 735,515 630,480'},
  {id:'hallway',anchor:[400,300],polygon:'275,215 355,225 410,270 450,310 435,355 390,390 330,370 285,320'}
 ],
 dxfRooms:[
  {id:'bedroom',polygon:'54,45 258,45 258,280 54,280'},
  {id:'bathroom',polygon:'295,45 378,45 378,280 295,280'},
  {id:'living',polygon:'380,45 684,45 684,287 380,287'},
  {id:'office',polygon:'54,288 268,288 268,492 54,492'},
  {id:'closet',polygon:'230,345 268,345 268,490 230,490'},
  {id:'big-pantry',polygon:'269,345 307,345 307,490 269,490'},
  {id:'hallway',polygon:'228,270 378,270 378,368 307,368 307,345 228,345'},
  {id:'kitchen',polygon:'377,368 682,368 682,545 377,545'},
  {id:'laundry',polygon:'685,370 813,370 813,545 685,545'}
 ]};
