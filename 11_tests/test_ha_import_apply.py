from importlib import import_module
from pathlib import Path


api = import_module("01_HCM.ha_import_api")


def test_imported_helpers_use_canonical_entity_ref_target_kind():
    assert api.IMPORT_HELPER_TARGET_KIND == "entity_ref"
    assert "/" not in api.IMPORT_HELPER_TARGET_KIND
    schema = Path("08_database/021_migration_mapping_registry.sql").read_text()
    assert "target_kind TEXT NOT NULL CHECK (target_kind ~ '^[a-z][a-z0-9_]{0,63}$')" in schema


def test_legacy_slash_qualified_helper_target_kind_is_not_supported():
    assert "helper/entity_ref" not in Path("01_HCM/mapping_registry.py").read_text()


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
