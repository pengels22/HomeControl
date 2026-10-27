/* Approved trace coordinate space: viewBox 110 130 1250 720.
   Room touch areas and illumination are overlays ONLY; never change approved_trace.svg.
   Entry is OUTSIDE apartment and UI panels are NOT rooms. */
window.STATIC_APARTMENT={
 viewBox:'110 130 1250 720',
 rooms:[
 {id:'bedroom',name:'Bedroom',polygon:'185,215 430,215 430,473 185,473',lights:[['Fan','switch.bedroom_fan_switch'],['Hubby Glow','light.hubby_glow_light'],['Wifey Glow','light.wifey_glow_light'],['Under Bed','light.bed_underglow_light'],['Lamps','light.bedroom_lamp_light'],['Bedroom Over','switch.bedroom_light']],zones:[['bedroom-over',306,344,109,104,'#ffd36a'],['bedroom-lamp-a',244,369,51,43,'#ffe29a'],['bedroom-lamp-b',365,368,52,43,'#ffe29a']]},
 {id:'bathroom',name:'Bathroom',polygon:'434,218 541,218 541,470 434,470',lights:[['Bathroom','preview.bathroom.over']],zones:[['bathroom-over',487,345,48,100,'#e3f4ff']]},
 {id:'office',name:'Office',polygon:'186,479 374,479 374,705 186,705',lights:[['Desk Lights','switch.modem_power_switch'],['Office Lights','switch.office_lights_switch_2'],['Printer Lights','switch.printer_lights_switch'],['Workbench','switch.workbench_switch']],zones:[['office-over',274,588,86,92,'#b9dcff'],['office-desk',250,553,49,51,'#ffd36a']]},
 {id:'closet',name:'Closet',polygon:'385,560 418,560 418,701 385,701',lights:[],zones:[]},
 {id:'big-pantry',name:'Big Pantry',polygon:'430,560 454,560 454,707 430,707',lights:[],zones:[]},
 {id:'hallway',name:'Hallway',polygon:'390,480 545,480 545,574 605,574 605,705 467,705 467,556 390,556',lights:[['Hallway','preview.hallway.over']],zones:[['hallway-over',529,537,88,59,'#fff0ba']]},
 {id:'living',name:'Living Room',polygon:'550,218 870,218 870,579 610,579 610,475 550,475',lights:[['Lamp','switch.lamp_switch'],['Living Room','switch.office_lights_switch'],["TV LED's",'light.tv_leds_light'],['Living Room Glow','light.living_room_glow'],['Records','light.living_room_records']],zones:[['living-over',733,378,139,149,'#ffd36a'],['living-lamp',615,383,65,66,'#ffe29a'],['living-tv',826,349,42,76,'#80d7ff']]},
 {id:'kitchen',name:'Kitchen / Dining',polygon:'614,635 867,635 867,766 614,766',lights:[['Kitchen','light.cabinets_lights_light'],['Dining','preview.kitchen.dining']],zones:[['kitchen-over',743,696,122,62,'#fff0ba'],['kitchen-dining',798,688,59,61,'#ffd36a']]},
 {id:'laundry',name:'Laundry',polygon:'883,591 1013,591 1013,761 883,761',lights:[['Laundry','switch.laundry_room']],zones:[['laundry-over',950,679,57,73,'#fff0ba']]},
 {id:'patio',name:'Patio',polygon:'888,222 997,222 997,571 888,571',lights:[['Patio','preview.patio.over']],zones:[['patio-over',950,407,49,134,'#a6d5ff']]}
 ]};
