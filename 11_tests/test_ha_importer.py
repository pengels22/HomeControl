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


def test_referenced_input_button_is_planned_without_external_mapping():
    plan = m.analyze_home_assistant({"automations": [{"id": "press", "triggers": [
        {"trigger": "state", "entity_id": "input_button.volume_up"}], "actions": []}]})
    item = plan["items"][0]
    assert item["eligibility"] == m.READY_WITH_TRANSLATIONS
    assert item["required_mappings"] == []
    assert item["planned_native_helpers"][0]["decision"] == "CREATE"
    assert item["planned_native_helpers"][0]["helper_type"] == "input_button"
    assert item["preview"]["triggers"][0]["entity_ref"]["planned_helper"] == "input_button.volume_up"


def test_literal_conversation_trigger_translates_to_native_phrases():
    plan = m.analyze_home_assistant({"automations": [{"id": "voice", "triggers": [
        {"trigger": "conversation", "command": [" Volume   Up ", "volume up"]}], "actions": []}]})
    item = plan["items"][0]
    assert item["eligibility"] == m.READY_WITH_TRANSLATIONS
    assert item["preview"]["triggers"] == [{"type": "conversation", "phrases": ["volume up"]}]


def test_helper_plan_is_deduplicated_across_source_items():
    plan = m.analyze_home_assistant({"automations": [
        {"id": "one", "triggers": [{"trigger": "state", "entity_id": "input_button.volume_up"}]},
        {"id": "two", "triggers": [{"trigger": "state", "entity_id": "input_button.volume_up"}]},
    ]})
    assert len(plan["helper_plans"]) == 1
    assert all(len(item["planned_native_helpers"]) == 1 for item in plan["items"])


def test_constrained_helper_without_definition_is_explicitly_blocked():
    plan = m.analyze_home_assistant({"automations": [{"id": "number", "triggers": [
        {"trigger": "state", "entity_id": "input_number.level"}], "actions": []}]})
    item = plan["items"][0]
    assert item["eligibility"] == m.BLOCKED_MAPPING
    assert m.HELPER_DEFINITION_REQUIRED in item["planned_native_helpers"][0]["warnings"]


def test_authoritative_helper_mapping_reuses_without_create_plan():
    plan = m.analyze_home_assistant(
        {"automations": [{"id": "press", "triggers": [{"trigger": "state", "entity_id": "input_button.volume_up"}]}]},
        mappings={"input_button.volume_up": {"entity_ref": 77, "confidence": "EXACT"}},
    )
    helper = plan["helper_plans"][0]
    assert helper["decision"] == "REUSE"
    assert helper["target_entity_ref"] == 77
    assert plan["items"][0]["preview"]["triggers"][0]["entity_ref"] == 77


def test_modern_ha_trigger_key_uses_trigger_family_not_event_type():
    plan = m.analyze_home_assistant({"automations": [{"id": "door", "triggers": [{"trigger": "device", "type": "opened", "device_id": "opaque"}], "actions": []}]})
    nested = plan["items"][0]["nested"]
    assert nested[0][0]["type"] == "device"
    assert nested[0][0]["status"] == m.NEEDS_MAPPING


def test_device_motion_trigger_translates_to_native_state_trigger_with_exact_mapping():
    plan = m.analyze_home_assistant({"automations": [{"id": "motion", "triggers": [{
        "trigger": "device", "type": "motion", "device_id": "d", "entity_id": "e", "domain": "binary_sensor"
    }], "actions": []}]}, mappings={"e": 42})
    trigger = plan["items"][0]["preview"]["triggers"][0]
    assert plan["items"][0]["compatibility"] == m.TRANSLATED
    assert trigger == {"type": "state", "entity_ref": 42, "to": "on"}


def test_device_action_translates_to_service_call_and_unresolved_is_mapping():
    source = {"automations": [{"id": "switch", "actions": [{
        "type": "turn_on", "device_id": "d", "entity_id": "e", "domain": "switch"
    }]}]}
    unresolved = m.analyze_home_assistant(source)
    assert unresolved["items"][0]["compatibility"] == m.NEEDS_MAPPING
    resolved = m.analyze_home_assistant(source, mappings={"e": 9})
    action = resolved["items"][0]["preview"]["actions"][0]
    assert resolved["items"][0]["compatibility"] == m.TRANSLATED
    assert action["domain"] == "switch" and action["service"] == "turn_on" and action["target_entity_ref"] == 9

def test_device_target_in_service_action_is_native_entity_reference():
    analyzer = m.HACompatibilityAnalyzer(
        mappings={"d": 10},
        service_mappings={"heos.group_volume_down": {"status": m.TRANSLATED, "domain": "media_player", "service": "group_volume_down"}},
    )
    plan = analyzer.analyze(
        {"automations": [{"id": "media", "actions": [{
            "action": "heos.group_volume_down",
            "target": {"device_id": "d"},
        }]}]}
    )
    action = plan["items"][0]["preview"]["actions"][0]
    assert action == {"type": "service", "domain": "media_player", "service": "group_volume_down", "target_entity_ref": 10, "service_data": {}}


def test_suggested_or_ambiguous_mapping_never_becomes_authoritative():
    source = {"automations": [{"id": "motion", "triggers": [{
        "trigger": "device", "type": "motion", "device_id": "d", "entity_id": "e", "domain": "binary_sensor"
    }], "actions": []}]}
    for confidence in ("SUGGESTED", "AMBIGUOUS"):
        plan = m.analyze_home_assistant(source, mappings={"e": {"entity_ref": 9, "confidence": confidence}})
        assert plan["items"][0]["compatibility"] == m.NEEDS_MAPPING


def test_device_tracker_zone_is_separate_from_presence_state():
    source = {"automations": [{"id": "zone", "triggers": [{
        "trigger": "device", "type": "enters", "device_id": "d", "entity_id": "e", "domain": "device_tracker", "zone": "zone.home"
    }], "actions": []}]}
    item = m.analyze_home_assistant(source, mappings={"e": 9})["items"][0]
    assert item["compatibility"] == m.NEEDS_MAPPING
    assert item["nested"][0][0]["type"] == "zone"


def test_registry_export_normalizes_opaque_entity_ids_without_reading_paths():
    registry = m.parse_registry_exports({"data": [{"id": "opaque", "entity_id": "binary_sensor.motion", "device_id": "dev"}]})
    plan = m.analyze_home_assistant({"automations": [{"id": "motion", "triggers": [{
        "trigger": "device", "type": "motion", "device_id": "dev", "entity_id": "opaque", "domain": "binary_sensor"
    }], "actions": []}]}, mappings={"binary_sensor.motion": 12}, registry=registry)
    assert plan["items"][0]["preview"]["triggers"][0]["entity_ref"] == 12
    with pytest.raises(m.HAImportError):
        m.parse_registry_exports("{}" * 2_000_000)


def test_duration_mapping_accepts_home_assistant_string_values():
    plan = m.analyze_home_assistant({"automations": [{"id": "delay", "actions": [{"delay": {"hours": "0", "minutes": "1", "seconds": "2"}}]}]})
    action = plan["items"][0]["preview"]["actions"][0]
    assert action["seconds"] == 62.0

def test_media_tts_and_notify_forms_normalize_to_generic_semantics():
    source = {"automations": [{"id": "media", "actions": [
        {"action": "media_player.play_media", "target": {"entity_id": "media_player.room"}, "data": {"media": {"media_content_id": "1", "media_content_type": "favorite"}, "enqueue": "play"}},
        {"action": "tts.cloud_say", "data": {"entity_id": "media_player.room", "message": "Ready"}},
        {"action": "notify.mobile_app_iphone_16", "data": {"title": "Status", "message": "Ready"}},
    ]}]}
    plan = m.analyze_home_assistant(source)
    actions = plan["items"][0]["preview"]["actions"]
    assert actions[0]["service"] == "play_media"
    assert actions[0]["service_data"]["media_content_type"] == "favorite"
    assert actions[1]["domain"] == "announcement" and actions[1]["service"] == "speak"
    assert actions[2]["domain"] == "notify" and actions[2]["service"] == "send"
    assert plan["items"][0]["eligibility"] == m.BLOCKED_MAPPING
    mapped = m.analyze_home_assistant(source, mappings={
        "media_player.room": 7,
        "notification_destination:notify.mobile_app_iphone_16": "11111111-1111-4111-8111-111111111111",
        "speech_backend:tts.cloud_say": "22222222-2222-4222-8222-222222222222",
    })["items"][0]["preview"]["actions"]
    assert mapped[1]["service_data"]["backend_id"].startswith("2222")
    assert mapped[2]["service_data"]["destination_id"].startswith("1111")


def test_zone_platform_and_device_forms_share_native_trigger():
    source = {"automations": [{"id": "zone", "triggers": [
        {"trigger": "zone", "entity_id": "device_tracker.phone", "zone": "zone.home", "event": "enter"},
        {"trigger": "device", "domain": "device_tracker", "entity_id": "device_tracker.phone", "zone": "zone.home", "type": "enters"},
    ], "actions": []}]}
    mappings = {"device_tracker.phone": 7, "zone.home": "00000000-0000-4000-8000-000000000001"}
    item = m.analyze_home_assistant(source, mappings=mappings)["items"][0]
    assert item["compatibility"] == m.TRANSLATED
    assert item["preview"]["triggers"][0] == item["preview"]["triggers"][1]
    assert item["preview"]["triggers"][0]["type"] == "zone"


def test_zone_without_mapping_is_blocked_mapping():
    source = {"automations": [{"id": "zone", "triggers": [
        {"trigger": "zone", "entity_id": "device_tracker.phone", "zone": "zone.home", "event": "leave"},
    ], "actions": []}]}
    item = m.analyze_home_assistant(source)["items"][0]
    assert item["eligibility"] == m.BLOCKED_MAPPING


def test_zha_button_forms_translate_to_normalized_device_events():
    source = {"automations": [{"id": "buttons", "triggers": [
        {"trigger": "device", "domain": "zha", "device_id": "remote", "type": "remote_button_short_press", "subtype": "button_1"},
        {"trigger": "device", "domain": "zha", "device_id": "remote", "type": "remote_button_double_press", "subtype": "button_1"},
        {"trigger": "device", "domain": "zha", "device_id": "remote", "type": "remote_button_long_press", "subtype": "button_1"},
    ], "actions": []}]}
    item = m.analyze_home_assistant(source, mappings={"device:remote": "device-ref"})["items"][0]
    assert item["compatibility"] == m.TRANSLATED
    assert [x["action"] for x in item["preview"]["triggers"]] == ["press", "double_press", "hold"]


def test_zha_unknown_event_remains_unsupported():
    source = {"automations": [{"id": "unknown", "triggers": [{
        "trigger": "device", "domain": "zha", "device_id": "remote", "type": "remote_button_release", "subtype": "button_1"
    }], "actions": []}]}
    item = m.analyze_home_assistant(source)["items"][0]
    assert item["compatibility"] == m.UNSUPPORTED
