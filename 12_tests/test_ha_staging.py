from importlib import import_module


staging = import_module("02_HCM.ha_staging")


def test_runtime_snapshot_overrides_initial_state_and_defaults_enabled():
    state = {"Vacation Mode": False}
    assert staging.resolve_source_state({"alias": "Vacation Mode", "initial_state": True}, state) == (False, "HA_RUNTIME_STATE")
    assert staging.resolve_source_state({"alias": "Other", "initial_state": False}, state) == (True, "HA_RUNTIME_STATE")
    assert staging.resolve_source_state({"alias": "Initial", "initial_state": False}) == (False, "HA_INITIAL_STATE")
    assert staging.resolve_source_state({"alias": "Default"}) == (True, "IMPORT_DEFAULT_ENABLED")


def _plan(*items):
    return {"items": [{"source_type": "automations", "source_id": item.get("id", "alias-fallback"),
                       "source_name": item.get("alias", ""), "source": item,
                       "source_fingerprint": "fp-" + str(abs(hash(repr(sorted(item.items(), key=lambda pair: pair[0]))))), "eligibility": "READY"}
                      for item in items]}


def test_identity_uses_explicit_id_and_preserves_duplicate_aliases():
    result = staging.audit_source_items(_plan({"id": "a", "alias": "Start Kitchen Timer"},
                                               {"id": "b", "alias": "Start Kitchen Timer"}), {})
    assert result["ok"]
    assert result["identities"] == ["a", "b"]
    assert list(result["duplicate_aliases"]) == ["Start Kitchen Timer"]


def test_snapshot_trims_alias_for_matching_but_keeps_source_name():
    plan = _plan({"id": "a", "alias": "Bedroom Tv Off Schedule "})
    result = staging.audit_source_items(plan, {"Bedroom Tv Off Schedule": False})
    assert result["ok"]
    assert result["state_assignments"] == {"a": False}
    assert plan["items"][0]["source_name"].endswith(" ")


def test_snapshot_stops_on_ambiguous_disabled_alias():
    result = staging.audit_source_items(_plan({"id": "a", "alias": "Duplicate"}, {"id": "b", "alias": "Duplicate"}), {"Duplicate": False})
    assert not result["ok"]
    assert result["errors"][0]["match_count"] == 2


def test_identity_survives_rename_and_fingerprint_change():
    first = staging.audit_source_items(_plan({"id": "stable", "alias": "Old"}), {})
    second_plan = _plan({"id": "stable", "alias": "New", "action": [{"service": "light.turn_on"}]})
    second = staging.audit_source_items(second_plan, {})
    assert first["identities"] == second["identities"] == ["stable"]
    assert first["items"][0]["source_fingerprint"] != second["items"][0]["source_fingerprint"]
