"""Purpose-built, read-only HCM target catalog helpers.

Catalogs contain mapping metadata only.  They are never used to invoke
providers or services, and web callers must provide data rather than a path.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 1
_SECRET_WORDS = ("token", "secret", "password", "credential", "authorization", "private_key", "api_key")


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()
                if not any(word in str(k).lower() for word in _SECRET_WORDS)}
    if isinstance(value, list): return [_safe(v) for v in value]
    return value


def _entry(row: dict, target_kind: str) -> dict:
    allowed = ("id", "target_kind", "target_ref", "entity_id", "display_name", "name", "domain", "device_id",
               "provider_id", "external_entity_id", "external_device_id", "availability", "enabled",
               "capabilities", "room_id", "safety_sensitive", "canonical_id")
    result = {key: _safe(row[key]) for key in allowed if key in row and row[key] is not None}
    result["target_kind"] = target_kind
    if "target_ref" not in result:
        result["target_ref"] = result.get("id") or result.get("entity_id") or result.get("device_id")
    return result


def catalog_from_rows(*, entities: Iterable[dict] = (), devices: Iterable[dict] = (), integrations: Iterable[dict] = (),
                      zones: Iterable[dict] = (), notification_destinations: Iterable[dict] = (), speech_backends: Iterable[dict] = (),
                      automations: Iterable[dict] = (), scripts: Iterable[dict] = (), scenes: Iterable[dict] = (),
                      helpers: Iterable[dict] = (), source_mode: str = "runtime", provenance: dict | None = None) -> dict:
    groups = {
        "entities": [_entry(row, "entity") for row in entities],
        "devices": [_entry(row, "device") for row in devices],
        "integrations": [_safe(dict(row)) for row in integrations],
        "zones": [_entry(row, "zone") for row in zones],
        "notification_destinations": [_entry(row, "notification_destination") for row in notification_destinations],
        "speech_backends": [_entry(row, "speech_backend") for row in speech_backends],
        "automations": [_entry(row, "automation") for row in automations],
        "scripts": [_entry(row, "script") for row in scripts],
        "scenes": [_entry(row, "scene") for row in scenes],
        "helpers": [_entry(row, "helper") for row in helpers],
    }
    counts = {key: len(value) for key, value in groups.items()}
    return {"schema_version": SCHEMA_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_mode": source_mode, "provenance": _safe(provenance or {}), "counts": counts, **groups}


def load_catalog(value: dict) -> dict:
    if not isinstance(value, dict): raise ValueError("target_catalog must be an object")
    result = catalog_from_rows(source_mode=str(value.get("source_mode", "export")), provenance=value.get("provenance"))
    result["generated_at"] = value.get("generated_at") or result["generated_at"]
    for key in result:
        if key in {"schema_version", "generated_at", "source_mode", "provenance", "counts"}: continue
        rows = value.get(key, [])
        if not isinstance(rows, list): raise ValueError(f"target_catalog.{key} must be a list")
        result[key] = [_safe(dict(row)) for row in rows if isinstance(row, dict)]
    result["schema_version"] = int(value.get("schema_version", SCHEMA_VERSION))
    result["counts"] = {key: len(result[key]) for key in result if key in {"entities", "devices", "integrations", "zones", "notification_destinations", "speech_backends", "automations", "scripts", "scenes", "helpers"}}
    return result


def candidates(catalog: dict) -> list[dict]:
    catalog = load_catalog(catalog)
    rows = []
    for key in ("entities", "devices", "zones", "notification_destinations", "speech_backends", "automations", "scripts", "scenes", "helpers"):
        rows.extend(dict(row) for row in catalog.get(key, []))
    return rows


def summary(catalog: dict) -> dict:
    catalog = load_catalog(catalog)
    return {"schema_version": catalog["schema_version"], "generated_at": catalog["generated_at"],
            "source_mode": catalog["source_mode"], "provenance": catalog.get("provenance", {}),
            "counts": catalog["counts"], "entity_domains": dict(Counter(row.get("domain", "unknown") for row in catalog.get("entities", []))),
            "providers": dict(Counter(row.get("provider_id", "native") for row in catalog.get("entities", []))) }
