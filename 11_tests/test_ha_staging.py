from importlib import import_module


staging = import_module("01_HCM.ha_staging")


def test_runtime_snapshot_overrides_initial_state_and_defaults_enabled():
    state = {"Vacation Mode": False}
    assert staging.resolve_source_state({"alias": "Vacation Mode", "initial_state": True}, state) == (False, "HA_RUNTIME_STATE")
    assert staging.resolve_source_state({"alias": "Other", "initial_state": False}, state) == (True, "HA_RUNTIME_STATE")
    assert staging.resolve_source_state({"alias": "Initial", "initial_state": False}) == (False, "HA_INITIAL_STATE")
    assert staging.resolve_source_state({"alias": "Default"}) == (True, "IMPORT_DEFAULT_ENABLED")
