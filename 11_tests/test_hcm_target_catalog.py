from importlib import import_module


catalog = import_module("01_HCM.hcm_target_catalog")


def test_catalog_is_purpose_built_and_redacts_secret_fields():
    value = catalog.catalog_from_rows(
        entities=[{"id": 4, "entity_id": "light.room", "domain": "light", "provider_id": "native", "api_token": "hidden"}],
        devices=[{"id": 8, "external_device_id": "stable-device"}],
        source_mode="export", provenance={"commit": "test"},
    )
    assert value["counts"]["entities"] == 1
    assert value["entities"][0]["target_ref"] == 4
    assert "api_token" not in str(value)
    assert catalog.summary(value)["entity_domains"] == {"light": 1}


def test_catalog_candidates_keep_special_target_kinds_separate():
    value = catalog.catalog_from_rows(
        notification_destinations=[{"destination_id": "d1", "name": "Phone"}],
        speech_backends=[{"backend_id": "b1", "name": "Voice"}],
        zones=[{"zone_id": "z1", "name": "Home"}],
    )
    rows = catalog.candidates(value)
    assert {row["target_kind"] for row in rows} == {"notification_destination", "speech_backend", "zone"}


def test_offline_catalog_loader_rejects_non_object_and_preserves_snapshot_metadata():
    loaded = catalog.load_catalog({"schema_version": 1, "generated_at": "2026-01-01T00:00:00Z", "source_mode": "export", "entities": []})
    assert loaded["generated_at"] == "2026-01-01T00:00:00Z"
    assert loaded["source_mode"] == "export"
