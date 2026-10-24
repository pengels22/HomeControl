from importlib import import_module
from pathlib import Path


api = import_module("02_HCM.ha_import_api")


def test_imported_helpers_use_canonical_entity_ref_target_kind():
    assert api.IMPORT_HELPER_TARGET_KIND == "entity_ref"
    assert "/" not in api.IMPORT_HELPER_TARGET_KIND
    schema = Path("09_database/021_migration_mapping_registry.sql").read_text()
    assert "target_kind TEXT NOT NULL CHECK (target_kind ~ '^[a-z][a-z0-9_]{0,63}$')" in schema


def test_legacy_slash_qualified_helper_target_kind_is_not_supported():
    assert "helper/entity_ref" not in Path("02_HCM/mapping_registry.py").read_text()


def test_existing_native_helper_is_reuse_without_durable_mapping():
    plan = {"items": [{"eligibility": "READY_WITH_TRANSLATIONS", "planned_native_helpers": [{
        "source_identity": "input_button.volume_up", "helper_type": "input_button",
        "proposed_entity_id": "input_button.volume_up", "decision": "CREATE"}],
        "preview": {"native_objects_to_create": [], "native_objects_to_reuse": []}}]}
    resolved = api._resolve_native_helper_plans(plan, [{"entity_ref": 1158, "entity_id": "input_button.volume_up", "helper_type": "input_button"}])
    helper = resolved["items"][0]["planned_native_helpers"][0]
    assert helper["decision"] == "REUSE"
    assert helper["target_entity_ref"] == 1158
    assert helper["reuse_evidence"] == "entity_id_and_helper_type"
    assert resolved["items"][0]["preview"]["native_objects_to_reuse"] == [helper]


def test_missing_input_button_is_planned_create():
    plan = {"items": [{"planned_native_helpers": [{
        "source_identity": "input_button.volume_down", "helper_type": "input_button",
        "proposed_entity_id": "input_button.volume_down", "decision": "CREATE"}],
        "preview": {}}]}
    resolved = api._resolve_native_helper_plans(plan, [])
    assert resolved["items"][0]["planned_native_helpers"][0]["decision"] == "CREATE"
    assert resolved["items"][0]["preview"]["native_objects_to_create"][0]["source_identity"] == "input_button.volume_down"


def test_helper_planner_does_not_resolve_missing_definition():
    plan = {"items": [{"planned_native_helpers": [{
        "source_identity": "input_number.custom_time", "helper_type": "input_number",
        "proposed_entity_id": "input_number.custom_time", "decision": "CREATE",
        "warnings": ["HELPER_DEFINITION_REQUIRED"]}], "preview": {}}]}
    resolved = api._resolve_native_helper_plans(plan, [])
    helper = resolved["items"][0]["planned_native_helpers"][0]
    assert helper["decision"] == "CREATE"
    assert helper["warnings"] == ["HELPER_DEFINITION_REQUIRED"]


def test_materialize_helper_refs_preserves_enabled_definition():
    preview = {
        "name": "Imported",
        "enabled": False,
        "triggers": [{"type": "state", "entity_ref": {"planned_helper": "input_button.volume_up"}}],
        "actions": [],
    }
    materialized = api._materialize_helpers(preview, {"input_button.volume_up": 42})
    assert materialized["enabled"] is False
    assert materialized["triggers"][0]["entity_ref"] == 42


def test_materialize_helper_refs_does_not_fabricate_unknown_targets():
    preview = {"triggers": [{"entity_ref": {"planned_helper": "input_button.unknown"}}]}
    assert api._materialize_helpers(preview, {}) == preview
