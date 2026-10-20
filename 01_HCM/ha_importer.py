"""Safe Home Assistant YAML compatibility analysis and import planning.

The analyzer is deliberately independent of PostgreSQL and provider handlers.  It
turns exported HA YAML into a serializable plan; callers must explicitly apply a
plan through the native stores.  No source definition is executed while parsing
or analyzing.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

import yaml

from .expressions import ExpressionEngine, ExpressionError

COMPATIBLE = "COMPATIBLE"
TRANSLATED = "TRANSLATED"
NEEDS_MAPPING = "NEEDS_MAPPING"
UNAVAILABLE_SERVICE = "UNAVAILABLE_SERVICE"
UNSUPPORTED = "UNSUPPORTED"

READY = "READY"
READY_WITH_TRANSLATIONS = "READY_WITH_TRANSLATIONS"
BLOCKED_MAPPING = "BLOCKED_MAPPING"
BLOCKED_UNSUPPORTED = "BLOCKED_UNSUPPORTED"
BLOCKED_SERVICE = "BLOCKED_SERVICE"

_STATUS_RANK = {COMPATIBLE: 0, TRANSLATED: 1, NEEDS_MAPPING: 2, UNAVAILABLE_SERVICE: 3, UNSUPPORTED: 4}
_ELIGIBILITY = {COMPATIBLE: READY, TRANSLATED: READY_WITH_TRANSLATIONS, NEEDS_MAPPING: BLOCKED_MAPPING,
                UNAVAILABLE_SERVICE: BLOCKED_SERVICE, UNSUPPORTED: BLOCKED_UNSUPPORTED}

# This is intentionally data, rather than a chain of importer-specific if/else
# branches.  A provider may add a service to HCM without changing HA parsing.
SERVICE_MAPPINGS: dict[str, dict[str, Any]] = {
    "light.turn_on": {"status": TRANSLATED, "domain": "light", "service": "turn_on"},
    "light.turn_off": {"status": TRANSLATED, "domain": "light", "service": "turn_off"},
    "light.toggle": {"status": TRANSLATED, "domain": "light", "service": "toggle"},
    "switch.turn_on": {"status": TRANSLATED, "domain": "switch", "service": "turn_on"},
    "switch.turn_off": {"status": TRANSLATED, "domain": "switch", "service": "turn_off"},
    "switch.toggle": {"status": TRANSLATED, "domain": "switch", "service": "toggle"},
    "input_boolean.turn_on": {"status": TRANSLATED, "domain": "input_boolean", "service": "turn_on"},
    "input_boolean.turn_off": {"status": TRANSLATED, "domain": "input_boolean", "service": "turn_off"},
    "input_boolean.toggle": {"status": TRANSLATED, "domain": "input_boolean", "service": "toggle"},
    "input_number.set_value": {"status": TRANSLATED, "domain": "input_number", "service": "set_value"},
    "input_text.set_value": {"status": TRANSLATED, "domain": "input_text", "service": "set_value"},
    "input_select.select_option": {"status": TRANSLATED, "domain": "input_select", "service": "select_option"},
    "input_datetime.set_datetime": {"status": TRANSLATED, "domain": "input_datetime", "service": "set_datetime"},
    "counter.increment": {"status": TRANSLATED, "domain": "counter", "service": "increment"},
    "counter.decrement": {"status": TRANSLATED, "domain": "counter", "service": "decrement"},
    "counter.reset": {"status": TRANSLATED, "domain": "counter", "service": "reset"},
    "counter.set_value": {"status": TRANSLATED, "domain": "counter", "service": "set_value"},
    "timer.start": {"status": TRANSLATED, "domain": "timer", "service": "start"},
    "timer.pause": {"status": TRANSLATED, "domain": "timer", "service": "pause"},
    "timer.cancel": {"status": TRANSLATED, "domain": "timer", "service": "cancel"},
    "timer.finish": {"status": TRANSLATED, "domain": "timer", "service": "finish"},
    "script.turn_on": {"status": TRANSLATED, "domain": "script", "service": "run"},
    "scene.turn_on": {"status": TRANSLATED, "domain": "scene", "service": "turn_on"},
    "automation.trigger": {"status": TRANSLATED, "domain": "automation", "service": "trigger"},
    "automation.turn_on": {"status": UNAVAILABLE_SERVICE},
    "automation.turn_off": {"status": UNAVAILABLE_SERVICE},
}

_READ_ONLY_TRIGGER_TYPES = {"zone": UNSUPPORTED, "conversation": UNSUPPORTED, "device": NEEDS_MAPPING, "manual": COMPATIBLE}
_SUPPORTED_HELPERS = {"input_boolean", "input_button", "input_number", "input_text", "input_select", "input_datetime", "counter", "timer", "schedule"}


class HAImportError(ValueError):
    """Malformed or unsafe source input."""


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        blocked = ("token", "secret", "password", "authorization", "api_key", "access_token", "refresh_token", "code")
        return {str(k): "[REDACTED]" if any(x in str(k).lower() for x in blocked) else _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def _depth(value: Any, level: int = 0) -> int:
    if level > 40:
        raise HAImportError("YAML nesting exceeds the safety limit")
    if isinstance(value, dict):
        return max([level] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(v, level + 1) for v in value])
    return level


def safe_load_yaml(source: str | bytes, *, max_bytes: int = 1_000_000) -> Any:
    """Parse YAML using PyYAML's safe loader with bounded input and depth."""
    if isinstance(source, bytes):
        raw = source
        text = source.decode("utf-8")
    elif isinstance(source, str):
        text = source
        raw = source.encode("utf-8")
    else:
        raise HAImportError("YAML source must be text or UTF-8 bytes")
    if len(raw) > max_bytes:
        raise HAImportError("YAML source exceeds the 1 MB safety limit")
    try:
        value = yaml.safe_load(text)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise HAImportError(f"Invalid or unsafe YAML: {exc}") from None
    _depth(value)
    return value


def _items(value: Any, source_type: str) -> list[tuple[str, dict[str, Any], int]]:
    """Normalize list and mapping HA forms to (id, object, source index)."""
    if value is None:
        return []
    out: list[tuple[str, dict[str, Any], int]] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise HAImportError(f"{source_type} item {index} must be a mapping")
            obj = deepcopy(item)
            source_id = str(obj.get("id") or obj.get("alias") or f"{source_type}_{index + 1}")
            out.append((source_id, obj, index))
    elif isinstance(value, dict):
        for index, (key, item) in enumerate(value.items()):
            if not isinstance(item, dict):
                raise HAImportError(f"{source_type} {key!r} must be a mapping")
            obj = deepcopy(item)
            source_id = str(obj.get("id") or key)
            obj.setdefault("id", source_id)
            out.append((source_id, obj, index))
    else:
        raise HAImportError(f"{source_type} must be a list or mapping")
    return out


def _combine(statuses: Iterable[str]) -> str:
    values = list(statuses)
    return max(values, key=lambda x: _STATUS_RANK.get(x, 4), default=COMPATIBLE)


def _source_fingerprint(source_type: str, source: Any) -> str:
    encoded = json.dumps(_safe(source), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256((source_type + ":").encode() + encoded).hexdigest()


class HACompatibilityAnalyzer:
    def __init__(self, *, mappings: dict[str, Any] | None = None, service_mappings: dict[str, dict[str, Any]] | None = None,
                 expression_engine: ExpressionEngine | None = None):
        self.mappings = mappings or {}
        self.service_mappings = {**SERVICE_MAPPINGS, **(service_mappings or {})}
        self.expressions = expression_engine or ExpressionEngine()
        self._entity_refs: set[str] = set()
        self._services: set[str] = set()

    def _map_entity(self, value: Any) -> tuple[str, Any, str]:
        entity = str(value)
        self._entity_refs.add(entity)
        mapped = self.mappings.get(entity)
        if isinstance(mapped, dict):
            target = mapped.get("target_entity_ref", mapped.get("entity_ref"))
            status = mapped.get("status", "EXACT" if target is not None else "UNRESOLVED")
        else:
            target, status = mapped, ("EXACT" if mapped is not None else "UNRESOLVED")
        if target is not None:
            return entity, target, COMPATIBLE
        return entity, None, NEEDS_MAPPING

    def _template(self, value: Any) -> tuple[Any, str, list[str], list[str]]:
        if not isinstance(value, str) or "{{" not in value and "{%" not in value:
            return value, COMPATIBLE, [], []
        try:
            compiled = self.expressions.compile(value, syntax="jinja")
            deps = self.expressions.dependencies(compiled)
            unresolved = [dep for dep in deps if self._map_entity(dep)[2] == NEEDS_MAPPING]
            return value, NEEDS_MAPPING if unresolved else TRANSLATED, deps, unresolved
        except ExpressionError as exc:
            return value, UNSUPPORTED, [], [str(exc)]

    def _target(self, action: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
        target: dict[str, Any] = {}
        statuses: list[str] = []
        mappings: list[str] = []
        raw = action.get("target") or {}
        if isinstance(raw, str): raw = {"entity_id": raw}
        if not isinstance(raw, dict): return target, UNSUPPORTED, ["target must be a mapping"]
        for key in ("entity_id", "device_id", "area_id"):
            values = raw.get(key)
            if values is None: continue
            if not isinstance(values, list): values = [values]
            resolved = []
            for value in values:
                if key == "entity_id":
                    source, target_ref, status = self._map_entity(value)
                    statuses.append(status); mappings.append(source)
                    if target_ref is not None: resolved.append(target_ref)
                elif key == "device_id":
                    mapping = self.mappings.get(str(value))
                    statuses.append(COMPATIBLE if mapping is not None else NEEDS_MAPPING)
                    if mapping is not None: resolved.append(mapping)
                    else: mappings.append(str(value))
                else:
                    mapping = self.mappings.get(f"area:{value}")
                    statuses.append(COMPATIBLE if mapping is not None else NEEDS_MAPPING)
                    if mapping is not None: resolved.append(mapping)
                    else: mappings.append(f"area:{value}")
            if resolved: target["target_entity_refs" if key == "entity_id" else key] = resolved
        return target, _combine(statuses), mappings

    def _service_action(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            domain, _, service = raw.partition(".")
            action = {"service": raw, "data": {}}
        elif isinstance(raw, dict):
            action = raw
            service_name = action.get("service") or action.get("action")
            if not isinstance(service_name, str):
                return {"status": UNSUPPORTED, "reason": "service action has no service name", "source": _safe(raw)}
            domain, _, service = service_name.partition(".")
        else:
            return {"status": UNSUPPORTED, "reason": "service action must be a mapping or string", "source": _safe(raw)}
        if not domain or not service:
            return {"status": UNSUPPORTED, "reason": "service name must be domain.service", "source": _safe(raw)}
        service_name = f"{domain}.{service}"; self._services.add(service_name)
        mapping = self.service_mappings.get(service_name)
        # HA exposes scripts as services named after the script entity.  They
        # still use the generic native script.run service at runtime.
        if mapping is None and domain == "script":
            mapping = {"status": TRANSLATED, "domain": "script", "service": "run"}
        if mapping is None:
            status = UNAVAILABLE_SERVICE
            reason = "No registered HCM service mapping"
            native = {}
        else:
            status = mapping.get("status", UNSUPPORTED)
            reason = mapping.get("reason")
            native = {"domain": mapping.get("domain", domain), "service": mapping.get("service", service)}
        target, target_status, target_refs = self._target(action)
        statuses = [status, target_status]
        data = deepcopy(action.get("data", action.get("service_data", {})) or {})
        if not isinstance(data, dict):
            statuses.append(UNSUPPORTED); data = {}
        expression_refs: list[str] = []
        for key, value in list(data.items()):
            rendered, template_status, deps, _ = self._template(value)
            data[key] = rendered; expression_refs.extend(deps); statuses.append(template_status)
        native_target = dict(target)
        refs = native_target.pop("target_entity_refs", None)
        if refs:
            if len(refs) > 1:
                statuses.append(NEEDS_MAPPING)
            native_target["target_entity_ref"] = refs[0] if len(refs) == 1 else refs
        result = {"type": "service", "status": _combine(statuses), "source": _safe(raw), "service": service_name,
                  "native": {**native, **native_target, "service_data": _safe(data)}, "target_mappings": target_refs,
                  "expression_references": sorted(set(expression_refs))}
        if reason: result["reason"] = reason
        if action.get("response_variable"):
            result["native"]["response_variable"] = str(action["response_variable"])
        return result

    def _action(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, str) or (isinstance(raw, dict) and ("service" in raw or "action" in raw)):
            return self._service_action(raw)
        if not isinstance(raw, dict): return {"status": UNSUPPORTED, "source": _safe(raw), "reason": "action must be a mapping"}
        if "delay" in raw:
            value = raw["delay"]
            return {"type": "delay", "status": TRANSLATED, "source": _safe(raw), "native": {"type": "delay", "seconds": _duration_seconds(value)}}
        if "condition" in raw:
            result = self._condition(raw["condition"])
            return {"type": "condition", "status": result["status"], "source": _safe(raw), "native": result.get("native"), "children": result.get("children", []), "reason": result.get("reason")}
        if "variables" in raw:
            statuses = []; values = {}
            for key, value in (raw.get("variables") or {}).items():
                rendered, status, deps, _ = self._template(value); values[str(key)] = rendered; statuses.append(status)
            return {"type": "variables", "status": _combine(statuses), "source": _safe(raw), "native": {"type": "variables", "variables": values}}
        if "stop" in raw: return {"type": "stop", "status": COMPATIBLE, "source": _safe(raw), "native": {"type": "stop"}}
        if "if" in raw:
            spec = raw["if"] if isinstance(raw["if"], dict) else {}
            condition = self._condition(spec.get("conditions", spec.get("condition", {})))
            then = self._actions(spec.get("then", [])); otherwise = self._actions(spec.get("else", []))
            return {"type": "if", "status": _combine([condition["status"], then["status"], otherwise["status"]]), "source": _safe(raw), "children": [condition, then, otherwise], "native": {"type": "if"}}
        if "choose" in raw:
            choices = [self._choice(choice) for choice in (raw.get("choose") or [])]; default = self._actions(raw.get("default", []))
            statuses = [default["status"]] + [x["status"] for x in choices]
            return {"type": "choose", "status": _combine(statuses), "source": _safe(raw), "children": choices + [default], "native": {"type": "choose"}}
        if "repeat" in raw:
            spec = raw["repeat"] if isinstance(raw["repeat"], dict) else {}
            bounded = spec.get("count") is not None or spec.get("for_each") is not None
            child = self._actions(spec.get("sequence", []))
            status = TRANSLATED if bounded else UNSUPPORTED
            return {"type": "repeat", "status": _combine([status, child["status"]]), "source": _safe(raw), "children": [child], "native": {"type": "repeat", "bounded": bounded}}
        if "parallel" in raw:
            branches = [self._actions(x) for x in (raw.get("parallel") or [])]
            return {"type": "parallel", "status": _combine([TRANSLATED] + [x["status"] for x in branches]), "source": _safe(raw), "children": branches, "native": {"type": "parallel"}}
        if "wait_template" in raw or "wait_for_trigger" in raw or "wait" in raw:
            return {"type": "wait", "status": UNSUPPORTED, "source": _safe(raw), "reason": "HCM V1 has no cancellable durable wait primitive"}
        return {"status": UNSUPPORTED, "source": _safe(raw), "reason": "Unknown Home Assistant action"}

    def _choice(self, choice: Any) -> dict[str, Any]:
        if not isinstance(choice, dict): return {"status": UNSUPPORTED, "source": _safe(choice)}
        condition = self._condition(choice.get("conditions", choice.get("condition", {}))); sequence = self._actions(choice.get("sequence", []))
        return {"status": _combine([condition["status"], sequence["status"]]), "children": [condition, sequence], "source": _safe(choice)}

    def _actions(self, values: Any) -> dict[str, Any]:
        if not isinstance(values, list): values = [values] if values else []
        children = [self._action(item) for item in values]
        return {"status": _combine([x["status"] for x in children]), "children": children, "native": [x.get("native") for x in children if x.get("native") is not None]}

    def _condition(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, list):
            children = [self._condition(x) for x in raw]
            return {"type": "and", "status": _combine([x["status"] for x in children]), "children": children, "native": {"type": "and"}}
        if not isinstance(raw, dict): return {"status": UNSUPPORTED, "source": _safe(raw), "reason": "condition must be a mapping"}
        typ = str(raw.get("condition", raw.get("type", ""))).lower()
        if typ in ("and", "or"):
            children = [self._condition(x) for x in raw.get("conditions", [])]
            return {"type": typ, "status": _combine([x["status"] for x in children]), "children": children, "native": {"type": typ}}
        if typ == "not":
            values = raw.get("conditions", [])
            if not isinstance(values, list): values = [values]
            children = [self._condition(x) for x in values]
            return {"type": typ, "status": _combine([x["status"] for x in children]), "children": children, "native": {"type": "not"}}
        if typ in ("state", "numeric_state"):
            source = raw.get("entity_id") or raw.get("entity")
            _, target, status = self._map_entity(source) if source else ("", None, NEEDS_MAPPING)
            native = {"type": typ, "entity_ref": target, **({"state": raw.get("state")} if typ == "state" else {"above": raw.get("above"), "below": raw.get("below")})} if target is not None else None
            return {"type": typ, "status": status, "source": _safe(raw), "native": native}
        if typ == "time": return {"type": typ, "status": COMPATIBLE, "source": _safe(raw), "native": {"type": "time"}}
        if typ == "template":
            source = raw.get("value_template", raw.get("template", "")); _, status, deps, _ = self._template(source)
            return {"type": typ, "status": status, "source": _safe(raw), "native": {"type": "template", "expression": source}, "expression_references": deps}
        return {"status": UNSUPPORTED, "source": _safe(raw), "reason": f"Unsupported condition type: {typ or 'unknown'}"}

    def _trigger(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict): return {"status": UNSUPPORTED, "source": _safe(raw), "reason": "trigger must be a mapping"}
        typ = str(raw.get("platform", raw.get("type", ""))).lower()
        if typ == "state":
            entities = raw.get("entity_id") or raw.get("entity")
            if isinstance(entities, list): entities = entities[0] if len(entities) == 1 else None
            _, target, status = self._map_entity(entities) if entities else ("", None, NEEDS_MAPPING)
            return {"type": typ, "status": status, "source": _safe(raw), "native": {"type": "state", "entity_ref": target, "from": raw.get("from"), "to": raw.get("to"), "attribute": raw.get("attribute"), "for": _duration_seconds(raw.get("for"))} if target is not None else None}
        if typ in ("time", "time_pattern"):
            return {"type": typ, "status": TRANSLATED, "source": _safe(raw), "native": {"type": typ, **{k: v for k, v in raw.items() if k != "platform"}}}
        if typ == "sun": return {"type": typ, "status": TRANSLATED, "source": _safe(raw), "native": {"type": "sun", "sun": raw.get("event"), "offset": raw.get("offset", 0)}}
        if typ == "event": return {"type": typ, "status": TRANSLATED, "source": _safe(raw), "native": {"type": "event", "event_type": raw.get("event_type"), "payload": raw.get("event_data", {})}}
        if typ in _READ_ONLY_TRIGGER_TYPES: return {"type": typ, "status": _READ_ONLY_TRIGGER_TYPES[typ], "source": _safe(raw), "reason": "No equivalent native trigger semantics"}
        return {"type": typ or "unknown", "status": UNSUPPORTED, "source": _safe(raw), "reason": "Unknown trigger type"}

    def _automation(self, source_id: str, obj: dict[str, Any], source_type: str, index: int) -> dict[str, Any]:
        triggers = obj.get("triggers", obj.get("trigger", [])); triggers = triggers if isinstance(triggers, list) else ([triggers] if triggers else [])
        conditions = obj.get("conditions", obj.get("condition", [])); actions = obj.get("actions", obj.get("action", [])); actions = actions if isinstance(actions, list) else ([actions] if actions else [])
        trigger_results = [self._trigger(x) for x in triggers]; condition_result = self._condition(conditions) if conditions else {"status": COMPATIBLE, "children": []}; action_result = self._actions(actions)
        statuses = [condition_result["status"], action_result["status"]] + [x["status"] for x in trigger_results]
        if not triggers: statuses.append(COMPATIBLE)  # manual-only automation
        preview = {"name": obj.get("alias", source_id), "description": obj.get("description"), "enabled": False,
                   "mode": obj.get("mode", "single"), "max_runs": min(int(obj.get("max", 10) or 10), 10),
                   "triggers": [x.get("native") for x in trigger_results if x.get("native")], "conditions": condition_result.get("native"),
                   "actions": action_result.get("native", [])}
        return self._item(source_type, source_id, obj, index, _combine(statuses), preview, trigger_results, condition_result, action_result)

    def _item(self, source_type: str, source_id: str, obj: dict[str, Any], index: int, status: str, preview: dict[str, Any], *nested: Any) -> dict[str, Any]:
        warnings = []; errors = []; unsupported = []
        def walk(value: Any):
            if isinstance(value, dict):
                if value.get("status") in (UNSUPPORTED, UNAVAILABLE_SERVICE, NEEDS_MAPPING):
                    unsupported.append({"status": value["status"], "reason": value.get("reason"), "type": value.get("type")})
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(list(nested))
        if status in (UNSUPPORTED, UNAVAILABLE_SERVICE): errors.append("One or more nested elements cannot be represented")
        if status == NEEDS_MAPPING: warnings.append("One or more entity or device mappings require confirmation")
        return {"source_type": source_type, "source_id": source_id, "source_name": obj.get("alias", obj.get("name", source_id)),
                "source_index": index, "source": _safe(obj), "source_fingerprint": _source_fingerprint(source_type, obj),
                "compatibility": status, "eligibility": _ELIGIBILITY[status], "confidence": "EXACT" if status == COMPATIBLE else "SUGGESTED" if status == TRANSLATED else "UNRESOLVED",
                "preview": preview, "warnings": warnings, "errors": errors, "referenced_entities": sorted(self._entity_refs),
                "referenced_services": sorted(self._services), "unsupported_features": unsupported, "required_mappings": sorted(self._entity_refs),
                "nested": _safe(nested)}

    def analyze(self, sources: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(sources, dict): raise HAImportError("Source payload must be a mapping")
        self._entity_refs.clear(); self._services.clear(); aggregate_entities: set[str] = set(); aggregate_services: set[str] = set(); items: list[dict[str, Any]] = []
        for source_type in ("automations", "scripts", "scenes"):
            value = sources.get(source_type, sources.get(f"{source_type}.yaml"))
            for source_id, obj, index in _items(value, source_type):
                self._entity_refs.clear(); self._services.clear()
                if source_type == "automations": item = self._automation(source_id, obj, source_type, index)
                elif source_type == "scripts":
                    action = self._actions(obj.get("sequence", obj.get("actions", []))); preview = {"name": obj.get("alias", source_id), "description": obj.get("description"), "enabled": False, "mode": obj.get("mode", "single"), "actions": action.get("native", [])}; item = self._item(source_type, source_id, obj, index, action["status"], preview, action)
                else:
                    targets = obj.get("entities", obj.get("target", [])); target_items = []
                    if isinstance(targets, dict): targets = [{"entity_id": k, **(v if isinstance(v, dict) else {"state": v})} for k, v in targets.items()]
                    for target in (targets if isinstance(targets, list) else []):
                        if not isinstance(target, dict): target_items.append({"status": UNSUPPORTED, "source": _safe(target)}); continue
                        entity_id = target.get("entity_id") or target.get("entity"); _, ref, status = self._map_entity(entity_id) if entity_id else ("", None, NEEDS_MAPPING); target_items.append({"status": status, "source": _safe(target), "native": {"entity_ref": ref, "state": target.get("state"), "attributes": target.get("attributes", {})} if ref is not None else None})
                    status = _combine([x["status"] for x in target_items]); preview = {"name": obj.get("name", source_id), "description": obj.get("description"), "targets": [x.get("native") for x in target_items if x.get("native")]}; item = self._item(source_type, source_id, obj, index, status, preview, target_items)
                aggregate_entities.update(self._entity_refs); aggregate_services.update(self._services); items.append(item)
        # Optional helper fragments use HA's domain-shaped configuration:
        # input_boolean: {guest_mode: {initial: true}}.  A complete
        # configuration.yaml is not required.
        helper_sources = sources.get("helpers")
        if helper_sources is None:
            helper_sources = {key: sources[key] for key in _SUPPORTED_HELPERS if key in sources}
        if helper_sources:
            if not isinstance(helper_sources, dict): raise HAImportError("helpers must be a mapping")
            for helper_type, definitions in helper_sources.items():
                if helper_type not in _SUPPORTED_HELPERS: continue
                for name, config in (definitions or {}).items():
                    if not isinstance(config, dict): config = {"initial": config}
                    source_id = f"{helper_type}.{name}"
                    item = self._item("helpers", source_id, config, len(items), COMPATIBLE,
                                      {"helper_type": helper_type, "name": str(name), "entity_id": source_id, "config": _safe(config)},
                                      {"status": COMPATIBLE, "type": "helper"})
                    items.append(item)
        counts = {status: sum(1 for item in items if item["compatibility"] == status) for status in (COMPATIBLE, TRANSLATED, NEEDS_MAPPING, UNAVAILABLE_SERVICE, UNSUPPORTED)}
        return {"schema_version": 1, "source_system": "home_assistant", "analyzed_at": datetime.now(timezone.utc).isoformat(), "items": items, "summary": counts, "referenced_entities": sorted(aggregate_entities), "referenced_services": sorted(aggregate_services), "import_eligible": [x["source_id"] for x in items if x["eligibility"] in (READY, READY_WITH_TRANSLATIONS)]}


def _duration_seconds(value: Any) -> float | None:
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, dict): return float(value.get("seconds", 0) + value.get("minutes", 0) * 60 + value.get("hours", 0) * 3600 + value.get("days", 0) * 86400)
    text = str(value)
    try:
        parts = [int(x) for x in text.split(":")]
        if len(parts) == 3: return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
        if len(parts) == 2: return float(parts[0] * 60 + parts[1])
        return float(text)
    except ValueError: return None


def analyze_home_assistant(sources: dict[str, Any], *, mappings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze structured YAML objects without mutating HCM."""
    return HACompatibilityAnalyzer(mappings=mappings).analyze(sources)


def analyze_yaml(*, automations: str | bytes | None = None, scripts: str | bytes | None = None, scenes: str | bytes | None = None,
                 mappings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {}
    for name, source in (("automations", automations), ("scripts", scripts), ("scenes", scenes)):
        if source is not None: payload[name] = safe_load_yaml(source)
    return analyze_home_assistant(payload, mappings=mappings)
