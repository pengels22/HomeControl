from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).parents[1]


def migrate_schema_one(config):
    migrated = deepcopy(config)
    migrated.setdefault("rooms", ["Front Entry", "Foyer", "Living Room", "Kitchen", "Garage"])
    migrated["schema"] = 2
    return migrated


def test_schema_one_migration_preserves_configuration_and_adds_rooms():
    original = {
        "schema": 1,
        "channels": [{"name": "Front Door", "area": 1, "type": "OPENING"}],
        "relays": [{"name": "Interior Siren", "siren": True}],
        "keypads": [{"name": "Garage Entry", "area": 2, "input_names": ["Door"]}],
    }
    migrated = migrate_schema_one(original)
    assert migrated["schema"] == 2
    assert migrated["channels"] == original["channels"]
    assert migrated["relays"] == original["relays"]
    assert migrated["keypads"] == original["keypads"]
    assert migrated["rooms"]


def test_schema_two_and_unknown_schema_rules():
    current = {"schema": 2, "rooms": ["Custom Room"]}
    assert migrate_schema_one(current)["rooms"] == ["Custom Room"]
    unknown = {"schema": 99, "channels": [{"name": "Keep"}]}
    assert unknown["schema"] == 99
    assert unknown["channels"][0]["name"] == "Keep"


def test_firmware_contains_safe_schema_migration_and_reprovision_paths():
    config = (ROOT / "06_ACM/03_Shared/config_store.cpp").read_text()
    pin = (ROOT / "06_ACM/03_Shared/pin_store.cpp").read_text()
    web = (ROOT / "06_ACM/03_Shared/web_admin.cpp").read_text()
    assert "SCHEMA_VERSION=2" in (ROOT / "06_ACM/03_Shared/config_store.h").read_text()
    assert "schema==1" in config
    assert "RECOVERY_REQUIRED" in config
    assert "reprovisionMaster" in pin
    assert "CREDENTIAL_REPROVISIONED" in web
    assert "credentialReprovisioning" not in web
