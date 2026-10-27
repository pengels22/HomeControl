/* Editable static-plan configuration. Coordinates match apartment_render.svg. */
window.STATIC_APARTMENT = {
  viewBox: '0 0 1200 760',
  rooms: [
    {id:'bedroom',name:'Bedroom',polygon:'100,100 315,100 315,310 100,310',lights:[['Fan','preview.bedroom.fan'],['Hubby Glow','preview.bedroom.hubby'],['Wifey Glow','preview.bedroom.wifey'],['Under Bed','preview.bedroom.underbed'],['Lamps','preview.bedroom.lamps'],['Bedroom Over','preview.bedroom.over']],zones:[['bedroom-over',205,200,150,115,'#ffd36a'],['bedroom-lamp-a',130,230,70,60,'#ffe29a'],['bedroom-lamp-b',280,230,70,60,'#ffe29a']]},
    {id:'office',name:'Office',polygon:'100,350 315,350 315,545 100,545',lights:[['Desk Lights','preview.office.desk'],['Office Lights','preview.office.over'],['Printer Lights','preview.office.printer'],['Workbench','preview.office.workbench']],zones:[['office-over',205,445,145,100,'#a7dcff'],['office-desk',170,405,100,55,'#ffd36a']]},
    {id:'bathroom',name:'Bathroom',polygon:'335,215 445,215 445,330 335,330',lights:[['Bathroom','preview.bathroom.over']],zones:[['bathroom-over',390,270,75,65,'#d6f3ff']]},
    {id:'hallway',name:'Hallway',polygon:'335,350 445,350 445,465 335,465',lights:[['Hallway','preview.hallway.over']],zones:[['hallway-over',390,405,75,70,'#fff0ba']]},
    {id:'living',name:'Living Room',polygon:'465,100 800,100 800,355 465,355',lights:[['Lamp','preview.living.lamp'],['Living Room','preview.living.over'],["TV LED's",'preview.living.tv'],['Living Room Glow','preview.living.glow'],['Records','preview.living.records']],zones:[['living-over',630,220,220,145,'#ffd36a'],['living-lamp',520,285,80,75,'#ffe29a'],['living-tv',765,185,60,65,'#6bdcff']]},
    {id:'kitchen',name:'Kitchen / Dining',polygon:'465,375 800,375 800,545 465,545',lights:[['Kitchen','preview.kitchen.over'],['Dining','preview.kitchen.dining']],zones:[['kitchen-over',625,445,220,100,'#fff0ba'],['kitchen-dining',530,480,85,65,'#ffd36a']]},
    {id:'patio',name:'Patio',polygon:'850,100 1080,100 1080,310 850,310',lights:[['Patio','preview.patio.over']],zones:[['patio-over',965,205,150,110,'#9ddcff']]},
    {id:'laundry',name:'Laundry',polygon:'850,350 1080,350 1080,545 850,545',lights:[['Laundry','preview.laundry.over']],zones:[['laundry-over',965,445,150,100,'#fff0ba']]}
  ]
};
