"""Async capability enrichment for an already-built HA migration plan."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

from .ha_importer import NEEDS_MAPPING, UNAVAILABLE_SERVICE, UNSUPPORTED, _combine


def _targets(native):
    value = native.get("target_entity_ref")
    if value is None: value = native.get("target_entity_refs")
    if value is None: return []
    return value if isinstance(value, list) else [value]


def _has_template(value):
    if isinstance(value, str):
        return "{{" in value or "{%" in value
    if isinstance(value, dict):
        return any(_has_template(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_template(item) for item in value)
    return False


async def enrich_plan(plan, services, *, concurrency=20):
    """Annotate mapped service operations; never invokes a service/provider."""
    result = deepcopy(plan)
    cache = {}
    semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 50)))

    async def check(target, domain, service, arguments):
        dynamic = _has_template(arguments)
        validation_arguments = {} if dynamic else arguments
        try: key = (int(target), domain, service, json.dumps(arguments or {}, sort_keys=True, default=str))
        except (TypeError, ValueError): key = (str(target), domain, service, repr(arguments))
        if key not in cache:
            async with semaphore:
                try:
                    cache[key] = await services.validate_capability(int(target), domain, service, validation_arguments or {})
                except Exception:
                    cache[key] = {"status": "CAPABILITY_VALIDATION_ERROR", "reason": "Capability validation failed"}
        result = dict(cache[key])
        if dynamic:
            result["runtime_value_validation_required"] = True
            if result.get("status") == "INVALID_ARGUMENT":
                result["status"] = "SUPPORTED"
                result["reason"] = "Dynamic expression requires runtime argument validation"
        return result

    async def enrich_node(node):
        if isinstance(node, (list, tuple)):
            for child in node: await enrich_node(child)
            return
        if not isinstance(node, dict): return
        native = node.get("native") if isinstance(node.get("native"), dict) else None
        if native and (native.get("type") == "service" or node.get("type") == "service") and native.get("domain") and native.get("service"):
            targets = _targets(native)
            if not targets:
                node["capability_status"] = "NOT_CHECKED"
                node["capability_results"] = []
            elif native.get("domain") in {"notify", "announcement"}:
                node["capability_status"] = "NOT_CHECKED"
                node["capability_results"] = [{"status": "NOT_CHECKED", "reason": "Destination/backend uses its dedicated registry"}]
            else:
                checks = await asyncio.gather(*[
                    check(target, native["domain"], native["service"], native.get("service_data", {}))
                    for target in targets
                ])
                node["capability_results"] = [{"target_entity_ref": target, **check_result} for target, check_result in zip(targets, checks)]
                statuses = {entry.get("status") for entry in checks}
                if "SUPPORTED" in statuses and len(statuses) == 1: overall = "SUPPORTED"
                elif "SUPPORTED_BUT_UNAVAILABLE" in statuses and statuses <= {"SUPPORTED", "SUPPORTED_BUT_UNAVAILABLE"}: overall = "SUPPORTED_BUT_UNAVAILABLE"
                elif "SERVICE_NOT_REGISTERED" in statuses: overall = "SERVICE_NOT_REGISTERED"
                elif "INVALID_ARGUMENT" in statuses: overall = "INVALID_ARGUMENT"
                elif "TARGET_MISSING" in statuses: overall = "TARGET_MISSING"
                elif "TARGET_DOES_NOT_SUPPORT" in statuses: overall = "TARGET_DOES_NOT_SUPPORT"
                else: overall = "CAPABILITY_VALIDATION_ERROR"
                node["capability_status"] = overall
                if overall in {"TARGET_DOES_NOT_SUPPORT", "TARGET_MISSING"}: node["status"] = NEEDS_MAPPING
                elif overall == "SERVICE_NOT_REGISTERED": node["status"] = UNAVAILABLE_SERVICE
                elif overall in {"INVALID_ARGUMENT", "CAPABILITY_VALIDATION_ERROR"}: node["status"] = UNSUPPORTED
        for key, child in list(node.items()):
            if key not in {"capability_results"}: await enrich_node(child)

    for item in result.get("items", []):
        await enrich_node(item.get("nested", []))
        statuses = []
        def collect(value):
            if isinstance(value, dict):
                # Only analyzer compatibility statuses participate in the
                # item roll-up.  Capability validation has its own status
                # namespace (SUPPORTED, TARGET_MISSING, ...).
                if value.get("status") in {"COMPATIBLE", "TRANSLATED", NEEDS_MAPPING, UNAVAILABLE_SERVICE, UNSUPPORTED}:
                    statuses.append(value["status"])
                for child in value.values(): collect(child)
            elif isinstance(value, (list, tuple)):
                for child in value: collect(child)
        collect(item.get("nested", []))
        if statuses:
            item["compatibility"] = _combine(statuses)
            item["eligibility"] = {"COMPATIBLE":"READY","TRANSLATED":"READY_WITH_TRANSLATIONS","NEEDS_MAPPING":"BLOCKED_MAPPING","UNAVAILABLE_SERVICE":"BLOCKED_SERVICE","UNSUPPORTED":"BLOCKED_UNSUPPORTED"}.get(item["compatibility"], item["eligibility"])
    return result
