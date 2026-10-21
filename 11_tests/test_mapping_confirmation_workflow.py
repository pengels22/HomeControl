from importlib import import_module

import pytest
from fastapi import HTTPException

ha_import = import_module("01_HCM.ha_import_api")
mapping_api = import_module("01_HCM.mapping_api")
registry = import_module("01_HCM.mapping_registry")


ADMIN = {"user": "tester", "role": "ADMIN"}


@pytest.mark.asyncio
async def test_confirmation_keeps_confidence_separate_from_origin_and_is_idempotent(monkeypatch):
    rows = []

    class FakeMappings:
        async def list_mappings(self, **_):
            return list(rows)

        async def create_mapping(self, payload, *, actor):
            assert payload["confidence"] == "SUGGESTED"
            assert payload["origin"] == "USER_CONFIRMED"
            row = {"mapping_id": "m1", "source_identifier": payload["source_identifier"],
                   "target_kind": payload["target_kind"], "target_ref": str(payload["target_ref"]),
                   "status": "VALID", "confidence": payload["confidence"], "origin": payload["origin"]}
            rows.append(row)
            return row

        async def add_alias(self, *args, **kwargs):
            raise AssertionError("idempotent confirmation must not mutate aliases")

    fake = FakeMappings()
    monkeypatch.setattr(ha_import, "mapping_registry", fake)
    body = {"source_kind": "device", "source_identifier": "ha-device", "target_kind": "entity_ref",
            "target_ref": 10, "confidence": "SUGGESTED"}
    created = await ha_import.mapping_confirm(body, ADMIN)
    assert created["origin"] == "USER_CONFIRMED"
    unchanged = await ha_import.mapping_confirm(body, ADMIN)
    assert unchanged["no_change"] is True
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_confirmation_rejects_conflicting_target_without_replace(monkeypatch):
    class FakeMappings:
        async def list_mappings(self, **_):
            return [{"mapping_id": "m1", "source_identifier": "ha-device", "target_kind": "entity_ref",
                     "target_ref": "10", "status": "VALID", "confidence": "EXACT", "origin": "USER_CONFIRMED"}]

    monkeypatch.setattr(ha_import, "mapping_registry", FakeMappings())
    with pytest.raises(HTTPException) as exc:
        await ha_import.mapping_confirm({"source_kind": "device", "source_identifier": "ha-device",
                                         "target_kind": "entity_ref", "target_ref": 11}, ADMIN)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_direct_mapping_endpoint_passes_valid_confidence(monkeypatch):
    seen = {}

    class FakeMappings:
        async def create_mapping(self, payload, *, actor):
            seen.update(payload)
            return {"status": "VALID", "confidence": payload["confidence"], "origin": payload["origin"]}

    monkeypatch.setattr(mapping_api, "mappings", FakeMappings())
    result = await mapping_api.create_mapping({"source_system": "home_assistant", "source_kind": "device",
                                                "source_identifier": "ha-device", "target_kind": "entity_ref",
                                                "target_ref": 10, "confidence": "EXACT", "origin": "USER_CONFIRMED"}, ADMIN)
    assert result["status"] == "VALID"
    assert seen["origin"] == "USER_CONFIRMED"


@pytest.mark.asyncio
async def test_integer_target_refs_are_coerced_before_asyncpg_query():
    received = []

    class Conn:
        async def fetchrow(self, query, value):
            received.append(value)
            return {"enabled": True, "available": True}

    assert await registry._target_exists(Conn(), "entity_ref", "10") == (True, True)
    assert received == [10]
    assert await registry._target_exists(Conn(), "entity_ref", "not-an-id") == (False, False)
