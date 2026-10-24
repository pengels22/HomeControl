from importlib import import_module

import pytest

commands = import_module("02_HCM.command_events")
automation = import_module("02_HCM.automation")
api = import_module("02_HCM.api")


def test_command_normalization_is_bounded_and_deterministic():
    assert commands.normalize_command(" Volume   Up ") == "volume up"
    assert commands.normalize_phrases(["Volume Up", " volume   up "]) == ["volume up"]
    with pytest.raises(ValueError):
        commands.normalize_command(" ")


def test_conversation_trigger_exact_matching_and_nonmatching():
    engine = object.__new__(automation.AutomationEngine)
    trigger = {"type": "conversation", "phrases": ["volume up"]}
    assert engine._trigger_matches(trigger, {"event_type": "hcm_native.command", "payload": {"normalized_text": "volume up"}})
    assert not engine._trigger_matches(trigger, {"event_type": "hcm_native.command", "payload": {"normalized_text": "volume down"}})


@pytest.mark.asyncio
async def test_command_endpoint_requires_control_and_emits_only_ingestion(monkeypatch):
    seen = {}

    async def ingest(*args, **kwargs):
        seen.update(kwargs)
        return {"accepted": True, "duplicate": False, "event_id": "event-1", "normalized_text": "test command"}

    monkeypatch.setattr(api.command_events, "ingest", ingest)
    result = await api.ingest_command(api.CommandIn(text="test command"), {"user": "tester", "role": "CONTROL"})
    assert result["accepted"] is True
    assert seen["source"] == "authenticated_command"
    with pytest.raises(Exception):
        await api.ingest_command(api.CommandIn(text="test command"), {"user": "viewer", "role": "READONLY"})
