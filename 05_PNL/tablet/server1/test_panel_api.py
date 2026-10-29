import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import panel_api


class PanelApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "panel.json"
        self.config.write_text(Path(__file__).resolve().parents[1].joinpath("panel_config_living_room.json").read_text())
        panel_api.PANEL_CONFIG_PATH = self.config
        panel_api.FIRE7_TOKEN = "fire7-test-token"
        panel_api._recent_actions.clear()
        self.states = {
            "light.living_room_glow_all": {"state": "off", "attributes": {"supported_color_modes": ["brightness"]}},
            "switch.lamp_switch": {"state": "off", "attributes": {}},
            "switch.office_lights_switch": {"state": "off", "attributes": {}},
            "switch.bedroom_camera_power": {"state": "off", "attributes": {}},
            "climate.nest_thermostat": {"state": "heat", "attributes": {"current_temperature": 70, "temperature": 69, "min_temp": 50, "max_temp": 90, "target_temp_step": 1, "hvac_modes": ["off", "heat", "cool", "heat_cool"], "fan_modes": ["auto", "on"]}},
            "media_player.living_room": {"state": "idle", "attributes": {"volume_level": 0.4, "source": "Wii", "source_list": ["Wii", "Fire TV Stick", "Xbox", "Game Cube", "PS2", "RetroPie", "Record Player"]}},
        }

    def tearDown(self):
        self.temp.cleanup()

    def fake_ha(self, path, method="GET", payload=None):
        if path == "/api/states":
            return 200, [{"entity_id": entity, **state} for entity, state in self.states.items()]
        if path == "/api/":
            return 200, {"message": "API running."}
        if path.startswith("/api/services/"):
            self.last_service = (path, payload)
            return 200, []
        raise AssertionError(path)

    def test_config_auth_and_shape(self):
        self.assertTrue(panel_api.panel_authorized("Bearer fire7-test-token"))
        self.assertFalse(panel_api.panel_authorized(None))
        status, payload = panel_api.get_panel("/panel/config")
        self.assertEqual(status, 200)
        self.assertEqual({c["entity_id"] for c in payload["controls"]}, set(self.states))
        self.assertEqual([item["source"] for item in payload["media_sources"]], [
            "Wii", "Fire TV Stick", "Xbox", "Game Cube", "PS2", "RetroPie", "Record Player", "Pandora"
        ])

    @patch.object(panel_api, "_ha_request")
    def test_states_are_batched_and_normalized(self, ha):
        ha.side_effect = self.fake_ha
        status, payload = panel_api.get_panel("/panel/states")
        self.assertEqual(status, 200)
        self.assertEqual([s["entity_id"] for s in payload["states"]], list(self.states))
        self.assertTrue(all("available" in state and "attributes" in state for state in payload["states"]))
        ha.assert_called_once_with("/api/states")

    @patch.object(panel_api, "_ha_request")
    def test_allowlisted_actions_map_to_fixed_services(self, ha):
        ha.side_effect = self.fake_ha
        status, _ = panel_api.post_panel("/panel/action", json.dumps({"entity_id": "switch.lamp_switch", "action": "turn_on"}).encode(), "fire7")
        self.assertEqual(status, 200)
        self.assertEqual(self.last_service, ("/api/services/switch/turn_on", {"entity_id": "switch.lamp_switch"}))
        panel_api.post_panel("/panel/action", json.dumps({"entity_id": "climate.nest_thermostat", "action": "set_temperature", "temperature": 70}).encode(), "fire7")
        self.assertEqual(self.last_service, ("/api/services/climate/set_temperature", {"entity_id": "climate.nest_thermostat", "temperature": 70.0}))
        panel_api.post_panel("/panel/action", json.dumps({"entity_id": "media_player.living_room", "action": "select_media_source", "source": "Wii"}).encode(), "fire7")
        self.assertEqual(self.last_service, ("/api/services/media_player/select_source", {"entity_id": "media_player.living_room", "source": "Wii"}))
        panel_api.post_panel("/panel/action", json.dumps({"entity_id": "media_player.living_room", "action": "volume_set", "volume_level": 0.55}).encode(), "fire7")
        self.assertEqual(self.last_service, ("/api/services/media_player/volume_set", {"entity_id": "media_player.living_room", "volume_level": 0.55}))

    @patch.object(panel_api, "_ha_request")
    def test_rejects_unsafe_or_invalid_requests(self, ha):
        ha.side_effect = self.fake_ha
        cases = [
            {"entity_id": "light.not_configured", "action": "turn_on"},
            {"entity_id": "switch.lamp_switch", "action": "set_brightness", "brightness_pct": 20},
            {"entity_id": "climate.nest_thermostat", "action": "set_temperature", "temperature": 91},
            {"entity_id": "climate.nest_thermostat", "action": "set_hvac_mode", "hvac_mode": "dry"},
            {"entity_id": "media_player.living_room", "action": "select_media_source", "source": "Smooth Jazz Instrumentals Radio"},
            {"entity_id": "media_player.living_room", "action": "volume_set", "volume_level": 1.1},
            {"entity_id": "switch.lamp_switch", "action": "turn_on", "service": "light.turn_on"},
        ]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(panel_api.PanelError):
                panel_api.post_panel("/panel/action", json.dumps(body).encode(), "fire7")
        with self.assertRaises(panel_api.PanelError) as error:
            panel_api.post_panel("/panel/action", b"not-json", "fire7")
        self.assertEqual(error.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
