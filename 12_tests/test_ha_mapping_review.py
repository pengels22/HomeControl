from importlib import import_module


importer = import_module("01_HCM.ha_importer")
review = import_module("01_HCM.ha_mapping_review")


def test_queue_groups_requirements_and_scores_impact_without_private_source_dump():
    plan = importer.analyze_home_assistant({"automations": [{"id": "one", "alias": "Lamp", "triggers": [{"trigger": "state", "entity_id": "sensor.room"}], "actions": []}]})
    queue = review.build_mapping_queue(plan, candidates=[{"target_kind": "entity", "target_ref": 7, "entity_id": "sensor.room", "name": "Room"}])
    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["source_kind"] == "entity"
    assert item["source_identifier"] == "sensor.room"
    assert item["candidates"][0]["reasons"] == ["exact_identity"]
    assert "source" not in item


def test_queue_keeps_sensitive_mapping_categories_separate():
    plan = importer.analyze_home_assistant({"automations": [{"id": "notify", "actions": [{"service": "notify.mobile", "data": {"message": "ok"}}]}]})
    item = review.build_mapping_queue(plan)["items"][0]
    assert item["source_kind"] == "notification_destination"
    assert "message" not in str(item)


def test_entity_candidates_are_filtered_to_source_domain():
    plan = importer.analyze_home_assistant({"automations": [{"id": "climate", "triggers": [{"trigger": "state", "entity_id": "climate.room"}], "actions": []}]})
    queue = review.build_mapping_queue(plan, candidates=[
        {"target_kind": "entity", "target_ref": 1, "entity_id": "media_player.living", "domain": "media_player", "provider_id": "heos"},
        {"target_kind": "entity", "target_ref": 2, "entity_id": "climate.hcm", "domain": "climate", "provider_id": "hcm_native"},
    ])
    candidates = queue["items"][0]["candidates"]
    assert [row["target"]["entity_id"] for row in candidates] == ["climate.hcm"]


def test_preview_is_nonpersistent_and_reports_newly_ready():
    source = {"automations": [{"id": "a", "triggers": [{"trigger": "state", "entity_id": "sensor.room"}], "actions": []}]}
    plan = importer.analyze_home_assistant(source)
    result = review.preview_mapping(plan, "sensor.room", 4, analyzer=lambda mapping: importer.analyze_home_assistant(source, mappings=mapping))
    assert result["persistent"] is False
    assert result["newly_ready"] == ["a"]
