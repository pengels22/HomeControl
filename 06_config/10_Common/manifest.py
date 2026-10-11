from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
DEVICE_TYPES = {"HCM", "SIM", "LCM", "RCM", "PNL", "RMC", "CONFLICT", "LAB"}
DEPLOYMENT_ACTIONS = {"install", "update", "verify", "rollback", "firmware"}
LINUX_DEVICE_TYPES = {"HCM", "SIM", "LCM", "RCM", "PNL", "CONFLICT", "LAB"}
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.(service|timer)$")
PACKAGE_RE = re.compile(r"^[0-9]{2}_[A-Z0-9_]+$")
SCRIPT_RE = re.compile(r"^[A-Za-z0-9_.-]+\.sh$")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    path: Path
    raw: dict[str, Any]

    @property
    def device_type(self) -> str:
        return str(self.raw["device_type"])

    @property
    def package(self) -> str:
        return str(self.raw["package"])

    @property
    def deployment(self) -> dict[str, Any]:
        return dict(self.raw.get("deployment") or {})

    @property
    def services(self) -> list[str]:
        return list(self.raw.get("services") or [])


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{name} must be a mapping")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{name} must be a non-empty list")
    return value


def _safe_relative_file(value: Any, field: str, *, required_suffix: str | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty relative file")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ManifestError(f"{field} must be a simple relative file name")
    if required_suffix and not value.endswith(required_suffix):
        raise ManifestError(f"{field} must end with {required_suffix}")
    return value


def _validate_services(raw: dict[str, Any]) -> None:
    for service in raw.get("services") or []:
        if not isinstance(service, str) or not SERVICE_RE.fullmatch(service):
            raise ManifestError(f"invalid service name: {service!r}")


def _validate_config_files(raw: dict[str, Any]) -> None:
    for item in raw.get("configuration_files") or []:
        if isinstance(item, str):
            source = item
        elif isinstance(item, dict):
            source = item.get("source")
            destination = item.get("destination")
            if destination:
                dest = Path(str(destination))
                if not dest.is_absolute():
                    raise ManifestError(f"configuration destination must be absolute: {destination!r}")
        else:
            raise ManifestError("configuration_files entries must be strings or mappings")
        _safe_relative_file(source, "configuration_files.source")


def validate_manifest(raw: dict[str, Any], *, path: Path | None = None) -> Manifest:
    raw = _require_mapping(raw, "manifest")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"unsupported schema_version {raw.get('schema_version')!r}")
    device_type = raw.get("device_type")
    if device_type not in DEVICE_TYPES:
        raise ManifestError(f"unsupported device_type {device_type!r}")
    package = raw.get("package")
    if not isinstance(package, str) or not PACKAGE_RE.fullmatch(package):
        raise ManifestError(f"invalid package {package!r}")
    if path and path.parent.name != package:
        raise ManifestError(f"manifest package {package} does not match folder {path.parent.name}")

    hardware = _require_mapping(raw.get("hardware"), "hardware")
    _require_list(hardware.get("supported_platforms"), "hardware.supported_platforms")
    _require_list(hardware.get("supported_os"), "hardware.supported_os")
    _require_list(hardware.get("architectures"), "hardware.architectures")

    deployment = _require_mapping(raw.get("deployment"), "deployment")
    adapter = deployment.get("adapter")
    if device_type == "RMC":
        if adapter != "firmware":
            raise ManifestError("RMC must use firmware adapter")
    elif adapter not in {"linux_systemd", "hcm_docker", "conflict_heartbeat", "lab1_simulation"}:
        raise ManifestError(f"unsupported deployment adapter {adapter!r}")
    for action in deployment.get("actions") or []:
        if action not in DEPLOYMENT_ACTIONS:
            raise ManifestError(f"unsupported deployment action {action!r}")
    if device_type in LINUX_DEVICE_TYPES:
        for key in ("install", "update", "verify", "rollback"):
            _safe_relative_file(deployment.get(key), f"deployment.{key}", required_suffix=".sh")

    rollback = _require_mapping(raw.get("rollback"), "rollback")
    if rollback.get("enabled") is not True:
        raise ManifestError("rollback.enabled must be true")
    if rollback.get("backup_required") is not True:
        raise ManifestError("rollback.backup_required must be true")

    safety = _require_mapping(raw.get("safety"), "safety")
    for key in ("preserve_device_identity", "preserve_network_configuration", "preserve_operational_state"):
        if safety.get(key) is not True:
            raise ManifestError(f"safety.{key} must be true")

    auth = _require_mapping(raw.get("authentication"), "authentication")
    if not auth.get("required"):
        raise ManifestError("authentication.required must be true")

    _validate_services(raw)
    _validate_config_files(raw)
    return Manifest(path=path or Path(raw.get("package", "manifest.yaml")) / "manifest.yaml", raw=raw)


def load_manifest(path: Path) -> Manifest:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML in {path}: {exc}") from exc
    return validate_manifest(raw, path=path)


def load_all_manifests(config_root: Path) -> dict[str, Manifest]:
    manifests: dict[str, Manifest] = {}
    for path in sorted(config_root.glob("[0-9][0-9]_*/manifest.yaml")):
        manifest = load_manifest(path)
        if manifest.device_type in manifests:
            raise ManifestError(f"duplicate device_type {manifest.device_type}")
        manifests[manifest.device_type] = manifest
    missing = DEVICE_TYPES - set(manifests)
    if missing:
        raise ManifestError(f"missing manifests for: {', '.join(sorted(missing))}")
    return manifests
