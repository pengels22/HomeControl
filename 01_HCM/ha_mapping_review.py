"""Sanitized, source-centric Home Assistant mapping review helpers.

This module is deliberately pure: it never reads HA files, connects to HA, or
mutates HCM.  API handlers may supply durable mapping rows and HCM registry
snapshots when available.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any, Iterable

from .ha_importer import BLOCKED_MAPPING, NEEDS_MAPPING


_MAX_ITEMS = 50
_MAX_CANDIDATES = 20


def _kind(identifier: str) -> tuple[str, str | None]:
    value = str(identifier)
    if value.startswith("notification_destination:"):
        return "notification_destination", "notify"
    if value.startswith("speech_backend:"):
        return "speech_backend", "speech"
    if value.startswith("alarm_credential:"):
        return "security_credential", "alarm_control_panel"
    if value.startswith("device:"):
        return "device", None
    if value.startswith("zone:"):
        return "zone", "zone"
    domain = value.split(".", 1)[0] if "." in value else None
    return "entity", domain


def _collect(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for key in ("source_mapping_key",):
            if value.get(key): out.add(str(value[key]))
        for key in ("required_mappings", "target_mappings", "referenced_entities"):
            values = value.get(key)
            if isinstance(values, (list, tuple, set)):
                out.update(str(item) for item in values if item)
        for child in value.values(): _collect(child, out)
    elif isinstance(value, (list, tuple)):
        for child in value: _collect(child, out)


def _mapping_for(identifier: str, mappings: dict[str, Any], records: dict[str, dict]) -> dict | None:
    raw = records.get(identifier) or mappings.get(identifier)
    if raw is None: return None
    if isinstance(raw, dict):
        return {"status": raw.get("status", "UNCONFIRMED"), "confidence": raw.get("confidence"),
                "target_kind": raw.get("target_kind"), "target_ref": raw.get("target_ref", raw.get("entity_ref")),
                "mapping_id": raw.get("mapping_id")}
    return {"status": "VALID", "confidence": "USER_CONFIRMED", "target_ref": raw}


def _candidate_score(source: str, candidate: dict, required_services: list[str]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    identity = str(candidate.get("entity_id") or candidate.get("external_id") or candidate.get("target_ref") or "")
    if identity == source or str(candidate.get("external_id", "")) == source:
        score += 100; reasons.append("exact_identity")
    if candidate.get("canonical_id") == source:
        score += 80; reasons.append("canonical_identity")
    if candidate.get("name") and str(candidate["name"]).casefold() == source.casefold():
        score += 20; reasons.append("exact_name")
    if required_services and candidate.get("capabilities"):
        missing = [service for service in required_services if service not in candidate["capabilities"]]
        if missing: reasons.append("missing_capability:" + ",".join(sorted(missing)))
        else: score += 10; reasons.append("capabilities_satisfied")
    return score, reasons


def build_mapping_queue(plan: dict, *, mappings: dict[str, Any] | None = None,
                        durable_records: Iterable[dict] | None = None,
                        candidates: Iterable[dict] | None = None, limit: int = 500) -> dict:
    mappings = mappings or {}
    records = {str(row.get("source_identifier")): row for row in (durable_records or []) if row.get("source_identifier")}
    grouped: dict[str, dict[str, Any]] = {}
    for item in plan.get("items", []):
        refs: set[str] = set(item.get("required_mappings") or []) | set(item.get("referenced_entities") or [])
        _collect(item.get("nested"), refs)
        for source in sorted(refs):
            if not source: continue
            row = grouped.setdefault(source, {"source_identifier": source, "occurrence_count": 0,
                "affected_items": [], "required_services": set(), "blocked_items": 0})
            row["occurrence_count"] += 1
            row["required_services"].update(str(x) for x in item.get("referenced_services", []) if x)
            if item.get("eligibility") == BLOCKED_MAPPING: row["blocked_items"] += 1
            if len(row["affected_items"]) < _MAX_ITEMS:
                row["affected_items"].append({"source_id": str(item.get("source_id", "")), "alias": str(item.get("source_name", item.get("source_id", "")))[:160]})
    pool = list(candidates or [])
    result = []
    for source, row in grouped.items():
        kind, domain = _kind(source)
        mapping = _mapping_for(source, mappings, records)
        required = sorted(row["required_services"])
        scored = []
        allowed_kinds = {"entity"}
        if kind == "device": allowed_kinds = {"device"}
        elif kind == "zone": allowed_kinds = {"zone"}
        elif kind == "notification_destination": allowed_kinds = {"notification_destination"}
        elif kind == "speech_backend": allowed_kinds = {"speech_backend"}
        elif kind == "security_credential": allowed_kinds = {"security_credential"}
        for candidate in pool:
            if candidate.get("target_kind") not in allowed_kinds: continue
            # Entity candidates must stay within the source domain.  Without
            # this guard, an unrelated provider entity (for example a HEOS
            # media player) appears as a zero-score candidate for every
            # climate, sensor, or device-tracker identity.
            if kind == "entity" and domain and candidate.get("domain") and candidate.get("domain") != domain:
                continue
            score, reasons = _candidate_score(source, candidate, required)
            scored.append({"target": {k: candidate.get(k) for k in ("target_kind", "target_ref", "entity_id", "device_id", "name", "provider_id") if candidate.get(k) is not None},
                           "score": score, "reasons": reasons, "compatible": not any(x.startswith("missing_capability:") for x in reasons)})
        scored.sort(key=lambda x: (-x["score"], str(x["target"].get("target_ref", x["target"].get("entity_id", "")))))
        scored = scored[:_MAX_CANDIDATES]
        unlocked = row["blocked_items"] if mapping and mapping.get("status") == "VALID" else 0
        score_inputs = {"occurrences": row["occurrence_count"], "affected_items": len(row["affected_items"]), "blocked_items": row["blocked_items"], "potentially_unlocked": unlocked}
        impact_score = score_inputs["potentially_unlocked"] * 250 + score_inputs["affected_items"] * 100 + score_inputs["occurrences"] * 2
        result.append({"source_key": f"home_assistant:{kind}:{source}", "source_kind": kind, "domain": domain,
            "source_identifier": source[:512], "display_name": source[:160], "occurrence_count": row["occurrence_count"],
            "affected_item_count": len(row["affected_items"]), "affected_items": row["affected_items"], "required_services": required,
            "blocker_category": "BLOCKED_MAPPING" if row["blocked_items"] else None, "mapping": mapping,
            "mapping_health": (mapping or {}).get("status", "UNCONFIRMED"), "candidates": scored,
            "impact": {"score": impact_score, "inputs": score_inputs, "claims": []}})
    result.sort(key=lambda x: (-x["impact"]["score"], x["source_key"]))
    fingerprints = sorted(str(item.get("source_fingerprint", "")) for item in plan.get("items", []))
    revision = hashlib.sha256(json.dumps(fingerprints, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 1, "analysis_revision": revision,
            "total": len(result), "items": result[:max(1, min(int(limit), 500))]}


def preview_mapping(plan: dict, source_identifier: str, target: Any, *, mappings: dict[str, Any] | None = None,
                    analyzer=None) -> dict:
    """Compare a temporary candidate mapping without persistence or execution."""
    if analyzer is None: raise ValueError("analyzer is required")
    before = {str(x.get("source_id")): x for x in plan.get("items", [])}
    revision = hashlib.sha256(json.dumps(sorted(str(item.get("source_fingerprint", "")) for item in plan.get("items", [])), separators=(",", ":")).encode()).hexdigest()
    merged = dict(mappings or {}); merged[source_identifier] = target
    # Caller supplies a re-analysis function over the original sources.
    after_plan = analyzer(merged)
    after = {str(x.get("source_id")): x for x in after_plan.get("items", [])}
    impacted = []
    for source_id, item in before.items():
        newer = after.get(source_id)
        if newer and newer.get("eligibility") != item.get("eligibility"):
            impacted.append({"source_id": source_id, "before": item.get("eligibility"), "after": newer.get("eligibility"), "remaining_blockers": newer.get("unsupported_features", [])})
    return {"source_identifier": source_identifier, "target": target, "persistent": False, "analysis_revision": revision,
            "impacted_items": impacted, "newly_ready": [x["source_id"] for x in impacted if x["after"] in ("READY", "READY_WITH_TRANSLATIONS")],
            "remaining_blockers": {x["source_id"]: x.get("unsupported_features", []) for x in after_plan.get("items", []) if x.get("eligibility") not in ("READY", "READY_WITH_TRANSLATIONS")}}
