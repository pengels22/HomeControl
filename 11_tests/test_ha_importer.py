from importlib import import_module

import pytest


m = import_module("01_HCM.ha_importer")


def test_safe_yaml_and_normalized_automation_preview():
    plan = m.analyze_yaml(
        automations="""
- id: evening
  alias: Evening lights
  trigger:
    - platform: state
      entity_id: light.living
      to: 'on'
  condition:
    - condition: state
      entity_id: input_boolean.guest
      state: 'off'
  action:
    - service: light.turn_on
      target: {entity_id: light.living}
""",
        mappings={"light.living": 12, "input_boolean.guest": 13},
    )
    item = plan["items"][0]
    assert item["compatibility"] == m.TRANSLATED
    assert item["eligibility"] == m.READY_WITH_TRANSLATIONS
    assert item["preview"]["enabled"] is False
    assert item["preview"]["actions"][0]["target_entity_ref"] == 12
    assert item["source_fingerprint"]


def test_unsupported_and_unavailable_are_not_dropped():
    plan = m.analyze_yaml(
        automations="""
- id: bad
  triggers:
    - platform: zone
      entity_id: person.pat
      zone: zone.home
  actions:
    - service: nonexistent.example
    - wait_template: "{{ states('sensor.x') == 'on' }}"
"""
    )
    item = plan["items"][0]
    assert item["eligibility"] == m.BLOCKED_UNSUPPORTED
    statuses = {part["status"] for part in item["unsupported_features"]}
    assert m.UNAVAILABLE_SERVICE in statuses
    assert m.UNSUPPORTED in statuses


def test_safe_loader_rejects_python_tags_and_redacts_secrets():
    with pytest.raises(m.HAImportError):
        m.safe_load_yaml("!!python/object/apply:os.system ['echo bad']")
    plan = m.analyze_home_assistant({"scripts": {"alarm": {"sequence": [{"service": "alarm_control_panel.alarm_arm", "data": {"code": "fake-secret"}}]}}})
    assert "fake-secret" not in str(plan)
    assert plan["items"][0]["eligibility"] == m.BLOCKED_SERVICE


def test_optional_helper_fragments_are_planned():
    plan = m.analyze_home_assistant({"helpers": {"input_boolean": {"guest_mode": {"initial": True}}}})
    item = plan["items"][0]
    assert item["source_type"] == "helpers"
    assert item["source_id"] == "input_boolean.guest_mode"
    assert item["preview"]["helper_type"] == "input_boolean"
    assert item["eligibility"] == m.READY


def test_modern_ha_trigger_key_uses_trigger_family_not_event_type():
    plan = m.analyze_home_assistant({"automations": [{"id": "door", "triggers": [{"trigger": "device", "type": "opened", "device_id": "opaque"}], "actions": []}]})
    nested = plan["items"][0]["nested"]
    assert nested[0][0]["type"] == "device"
    assert nested[0][0]["status"] == m.NEEDS_MAPPING


def test_duration_mapping_accepts_home_assistant_string_values():
    plan = m.analyze_home_assistant({"automations": [{"id": "delay", "actions": [{"delay": {"hours": "0", "minutes": "1", "seconds": "2"}}]}]})
    action = plan["items"][0]["preview"]["actions"][0]
    assert action["seconds"] == 62.0
