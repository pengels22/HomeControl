"""Reference HCM dashboard matching the supplied Home Assistant layouts."""
from __future__ import annotations

from typing import Any


def _card(card_id: str, card_type: str, title: str, entity: str, x: int, y: int, w: int, h: int, **extra: Any) -> dict[str, Any]:
    return {"id": card_id, "type": card_type, "title": title, "entity": entity,
            "bounds": {"x": x, "y": y, "w": w, "h": h}, **extra}


def _button(card_id: str, title: str, entity: str, x: int, y: int, w: int, h: int, **extra: Any) -> dict[str, Any]:
    return _card(card_id, "button", title, entity, x, y, w, h, **extra)


def _room_grid(prefix: str, title: str, items: list[tuple[str, str]], x: int, y: int, w: int, h: int, *, rows: int = 4) -> dict[str, Any]:
    gap, cols = 8, 3
    cell_w, cell_h = (w - gap * (cols - 1)) // cols, (h - gap * (rows - 1)) // rows
    cards = []
    for index, (label, entity) in enumerate(items):
        row, col = divmod(index, cols)
        cards.append(_button(f"{prefix}-{index}", label, entity,
                             x + col * (cell_w + gap), y + row * (cell_h + gap), cell_w, cell_h))
    return {"id": prefix, "type": "entities", "title": title, "entities": [item["entity"] for item in cards], "items": cards,
            "bounds": {"x": x, "y": y, "w": w, "h": h}}


def build_reference_dashboard() -> dict[str, Any]:
    home = [
        _card("weather", "entity", "Weather", "weather.openweathermap", 16, 16, 326, 190),
        _button("morning", "Morning", "automation.auto_morning", 16, 214, 157, 66, icon="mdi:sun-compass"),
        _button("bedtime", "Bedtime", "automation.full_bed", 185, 214, 157, 66, icon="mdi:moon-waning-crescent"),
        _button("groceries", "Groceries", "shopping_list", 16, 294, 326, 190, icon="mdi:cart"),
        _card("climate", "entities", "Climate Readings", "area.current", 350, 16, 224, 300,
              entities=["sensor.average_temp", "sensor.average_humidity", "sensor.outside_temp_temperature", "sensor.outside_temp_humidity"]),
        _card("nest", "thermostat", "Home Nest", "climate.nest_thermostat", 584, 16, 208, 300),
        _button("windows", "Windows are Closed", "binary_sensor.windows_and_doors", 350, 328, 442, 72),
        _card("media", "entity", "Living Room", "media_player.living_room", 802, 16, 206, 250),
        _card("sources", "entities", "Media Sources", "media_player.living_room", 802, 274, 206, 104,
              entities=["automation.dvd_player", "automation.fire_stick", "automation.xbox", "automation.game_cube", "automation.ps2", "automation.listen_to_music", "automation.retropie"]),
        _card("alarmo", "entities", "Alarmo", "alarm_control_panel.alarmo", 802, 390, 206, 194,
              entities=["alarm_control_panel.alarmo", "alarm_control_panel.alarmo.arm_home", "alarm_control_panel.alarmo.arm_away", "alarm_control_panel.alarmo.arm_vacation"]),
    ]
    living = [("Lamp", "switch.lamp_switch"), ("Stove", "light.cabinets_lights_light"), ("TV LED's", "light.tv_leds_light"),
              ("Living Room", "switch.office_lights_switch"), ("Jack And Sally", "switch.scenic_1_switch"), ("Desk Led", "light.desk_leds_light"),
              ("Seasonal", "switch.seasonal_switches"), ("Laundry", "switch.laundry_room"), ("Living Room Glow", "light.living_room_glow"),
              ("Records", "light.living_room_records"), ("Living Room Glow All", "light.living_room_glow_all")]
    bedroom = [("Fan", "switch.bedroom_fan_switch"), ("Wreath", "switch.barbecue_lights_switch"), ("Hubby Glow", "light.hubby_glow_light"),
               ("Wifey Glow", "light.wifey_glow_light"), ("Under Bed", "light.bed_underglow_light"), ("Vines", "switch.bedroom_vines_switch"),
               ("Lamps", "light.bedroom_lamp_light"), ("Head White", "light.headboard_white_light"), ("Bedroom Over", "switch.bedroom_light"),
               ("Bedroom TV", "switch.bedroom_tv_switch")]
    office = [("Desk Lights", "switch.modem_power_switch"), ("Office Lights", "switch.office_lights_switch_2"), ("Printer Lights", "switch.printer_lights_switch"),
              ("Workbench", "switch.workbench_switch"), ("TV Schedule", "automation.bedroom_tv_off_schedule"), ("Desk Over", "light.office_desk_lights"),
              ("Compressor", "switch.air_compressor_switch"), ("Laser Fan", "light.office_laser_fan"), ("Bathroom Toe", "light.bathroom_toe")]
    lights = [_room_grid("living-room", "Living Room", living, 16, 16, 322, 478),
              _room_grid("bedroom", "Bedroom", bedroom, 350, 16, 322, 396),
              _button("curtains", "Closed · 1/4 · 1/2 · 3/4 · Open", "select.bedroom_curtain_bedroom_curtain_position_preset", 350, 424, 322, 70),
              _room_grid("office", "Office", office, 684, 16, 324, 396)]
    calendar = [_card("calendar-month", "entities", "Patrick", "calendar.personal", 16, 16, 992, 568,
                      entities=["calendar.personal", "calendar.rhino_staging"])]
    cooking = [_card("custom-timer", "entities", "Custom Timer", "input_datetime.kitchen_timer", 352, 36, 320, 230,
                     entities=["input_datetime.kitchen_timer", "input_number.kitchen_timer"]),
               _button("timer-3", "3 Min Timer", "timer.3_min_timer", 352, 282, 152, 76),
               _button("timer-5", "5 Min Timer", "input_boolean.5_min", 520, 282, 152, 76),
               _button("timer-10", "10 Min Timer", "input_boolean.10_min", 352, 374, 152, 76),
               _button("timer-cancel", "Cancel Timers", "timer.kitchen_timer", 520, 374, 152, 76)]
    return {"version": 1, "theme": "ha-dark", "pages": [
        {"id": "home", "title": "Home", "cards": home},
        {"id": "lights", "title": "Lights", "cards": lights},
        {"id": "calendar", "title": "Calendar", "cards": calendar},
        {"id": "cooking", "title": "Cooking", "cards": cooking},
    ]}


REFERENCE_DASHBOARD = build_reference_dashboard()
