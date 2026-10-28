# HomeControl Monitor Entity Checklist

Temporary inventory of the entities currently mapped by the 21-inch monitor UI.

## Bedroom

- [ x] `switch.bedroom_fan_switch` — Fan
- [ ] `light.hubby_glow_light` — Hubby Glow
- [ ] `light.wifey_glow_light` — Wifey Glow
- [ ] `light.bed_underglow_light` — Under Bed
- [ x] `light.bedroom_lamp_light` — Lamps
- [ x] `switch.bedroom_light` — Bedroom Over

## Bathroom

- [ ] `preview.bathroom.over` — Bathroom preview entity

## Office

- [x ] `switch.modem_power_switch` — Desk Lights
- [ x] `switch.office_lights_switch_2` — Office Lights
- [ x] `switch.printer_lights_switch` — Printer Lights
- [x ] `switch.workbench_switch` — Workbench

## Living Room

- [ x] `switch.lamp_switch` — Lamp
- [ x] `switch.office_lights_switch` — Living Room
- [ ] `light.tv_leds_light` — TV LEDs
- [ ] `light.living_room_glow` — Living Room Glow
- [ x] `light.living_room_records` — Records

## Kitchen / Dining

- [ x] `light.cabinets_lights_light` — Kitchen
- [ ] `preview.kitchen.dining` — Dining preview entity

## Laundry

- [ x] `switch.laundry_room` — Laundry

## Rooms without mapped monitor controls

- [ ] Closet — no light entities mapped
- [ ] Big Pantry — no light entities mapped
- [ ] Hallway — preview entity exists in the source configuration but is not included in the calibrated 3D room overlay
- [ ] Patio — preview entity exists in the source configuration but is not included in the calibrated 3D room overlay

## Global monitor controls

- [ x] `climate.nest_thermostat` — thermostat controls
- [ x] `alarm_control_panel.alarmo` — Alarmo controls
- [ x] `timer.3_min_timer` — 3-minute timer
- [x ] `timer.5_min_timer` — 5-minute timer
- [x ] `timer.10_min_timer` — 10-minute timer
- [ x] `timer.kitchen_timer` — kitchen timer
- [ x] `automation.fire_stick` — TV
- [ x] `automation.xbox` — Xbox
- [ x] `automation.game_cube` — Cube
- [ x] `automation.ps2` — PS2
- [ x] `automation.listen_to_music` — Music
- [ x] `automation.retropie` — Pi

## Climate sensor entities used by the monitor

- [x ] `sensor.average_temp` — inside temperature
- [ x] `sensor.average_humidity` — inside humidity
- [ x] `sensor.outside_temp_temperature` — outside temperature
- [ x] `sensor.outside_temp_humidity` — outside humidity
