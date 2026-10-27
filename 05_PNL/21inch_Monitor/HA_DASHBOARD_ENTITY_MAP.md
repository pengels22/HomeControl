# Home Assistant dashboard: supplied entity wiring map (2026-10-27)

Source: user's Home Assistant Lovelace YAML supplied in chat. This is a **configuration reference**, not evidence that each entity is currently operational. The separate authenticated `GET /api/states` test from HAMonitor showed several lights responding; validate all mappings and service permissions against current Home Assistant state before enabling writes.

## Rooms: exact labels and entities from Lights view
| Room section | UI name | Entity | Action/notes |
|---|---|---|---|
| Living | Lamp | `switch.lamp_switch` | switch.toggle |
| Living | Stove | `light.cabinets_lights_light` | light.toggle, historical transition 21s |
| Living | TV LED's | `light.tv_leds_light` | Button; tap action unspecified in supplied YAML |
| Living | Living Room | `switch.office_lights_switch` | switch.toggle; **name/entity appears mismatched**, verify |
| Living | Jack And Sally | `switch.scenic_1_switch` | Button; separate HA entity `light.jack_and_sally` was seen live; **do not assume equivalence** |
| Living | Desk Led | `light.desk_leds_light` | light.toggle |
| Living | Seasonal | `switch.seasonal_switches` | switch.toggle |
| Living | Laundry | `switch.laundry_room` | switch.toggle |
| Living | Glow | `light.living_room_glow` | light.toggle |
| Living | Records | `light.living_room_records` | light.toggle |
| Living | Glow All | `light.living_room_glow_all` | light.toggle |
| Bedroom | Fan | `switch.bedroom_fan_switch` | switch.toggle |
| Bedroom | Wreath | `switch.barbecue_lights_switch` | switch.toggle |
| Bedroom | Hubby Glow | `light.hubby_glow_light` + `light.bed_underglow_light` | combined toggle |
| Bedroom | Wifey Glow | `light.wifey_glow_light` + `light.bed_underglow_light` | combined toggle |
| Bedroom | Under Bed | `light.bed_underglow_light` | tap details, hold toggle |
| Bedroom | Vines | `switch.bedroom_vines_switch` | switch.toggle |
| Bedroom | Lamps | `light.bedroom_lamp_light` | tap details, hold toggle |
| Bedroom | Head White | `light.headboard_white_light` | tap details, hold toggle |
| Bedroom | Bedroom Over | `switch.bedroom_light` | switch.toggle |
| Bedroom | Bedroom TV | `switch.bedroom_tv_switch` | Button; tap unspecified |
| Bedroom | Curtains | `select.bedroom_curtain_bedroom_curtain_position_preset` | select.select_option: Closed, 1/4 Open, 1/2 Open, 3/4 Open, Open |
| Office | Desk Lights | `switch.modem_power_switch` | switch.toggle |
| Office | Office Lights | `switch.office_lights_switch_2` | switch.toggle |
| Office | Printer Lights | `switch.printer_lights_switch` | switch.toggle |
| Office | Workbench | `switch.workbench_switch` | Button |
| Office | Desk Over | `light.office_desk_lights` | light.toggle |
| Office | Compressor | `switch.air_compressor_switch` | Button; do not enable without review |
| Office | Laser Fan | `light.office_laser_fan` | Button; do not enable without review |
| Office | Bathroom Toe | `light.bathroom_toe` | Button |
| Office | TV Schedule | `automation.bedroom_tv_off_schedule` | automation.toggle |

**Room assignment caveat:** Above table preserves sections in supplied YAML; some entities listed under Living or Office are evidently located elsewhere. Do not assign an SVG hotspot to these solely by YAML section. Confirm physical room placement. Neither `light.living_room_group` nor `light.kitchen_group` were the named targets of the supplied Lights view but both appeared in the user's live read.

## Climate
- Thermostat: `climate.nest_thermostat`
- Inside temperature: `sensor.average_temp`
- Inside humidity: `sensor.average_humidity`
- Outside temperature: `sensor.outside_temp_temperature`
- Outside humidity: `sensor.outside_temp_humidity`
- Doors/windows summary: `binary_sensor.windows_and_doors`
- Weather: `weather.openweathermap`

Do not bypass HCM's thermostat authority or HVAC safety rules. Verify current controller ownership before enabling mutations.

## Media (current Home view)
- Player: `media_player.living_room`
- Wii: `automation.dvd_player`
- TV: `automation.fire_stick`
- Xbox: `automation.xbox`
- Cube: `automation.game_cube`
- PS2: `automation.ps2`
- Music: `automation.listen_to_music`
- Pi: `automation.retropie`
- Player volume: `media_player.volume_down`, `media_player.volume_up` on `media_player.living_room`
- Older `decluttering_templates` block uses distinct automations (e.g. `automation.watch_movie`, `automation.watch_tv`); **prefer active Home view**, but verify.

These are automation triggers, not `media_player.select_source` commands. The supplied YAML includes `skip_condition: true` for several actions: retain existing intent only after reviewing backend authorization and safety.

## Alarm
- `alarm_control_panel.alarmo`; modes in source: arm_home, arm_away, arm_vacation.
- Never expose the long-lived HA token or PIN in browser source, storage, or logs. Implement server-side policy and explicit acknowledgement before enabling arm/disarm.

## Calendar
- `calendar.rhino_staging`
- `calendar.personal`
- Historical Lovelace calendar view is a month calendar; authenticated calendar event API still needs implementation.

## Cooking
- Custom time input: `input_datetime.kitchen_timer`
- Custom timer script: `script.kitchen_timer_2`
- Timer entities: `timer.3_min_timer`, `timer.5_min_timer`, `timer.10_min_timer`, `timer.kitchen_timer`
- Presets use `timer.start`; cancel uses `timer.cancel` for all four timer entities.
- `input_number.kitchen_timer`, `input_boolean.5_min`, `input_boolean.10_min`, `input_boolean.cancel_time` appear as display/control context (not timer targets).
- Traeger/Grilly Wonka shows switch and sensors; read-only first.

## Connection and implementation status
- The Pi's local test Flask server on port `8766` was shown retrieving authenticated `/api/entities` data.
- At that point the Flask backend was read-only, on a **test port**, and the `8765` kiosk still ran `python3 -m http.server`.
- A Lovelace YAML file is not a valid HA authentication credential or a guarantee that an entity remains available.
- Add authenticated scoped backend `/api` functionality and frontend live-state adapter. Do not embed token in `static_apartment.js`.
- Verify entity state, action eligibility, ACK/readback, and offline handling before enabling each control.
