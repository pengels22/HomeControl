from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from . import inventory as inventory_mod
    from . import manifest as manifest_mod
    from . import release as release_mod
except ImportError:  # Allows direct loading from homecontrol_cli.py.
    import inventory as inventory_mod  # type: ignore
    import manifest as manifest_mod  # type: ignore
    import release as release_mod  # type: ignore


PASS = "PASS"
SKIPPED = "SKIPPED"
NO_CHANGE = "NO CHANGE"
MANUAL = "MANUAL INTERVENTION REQUIRED"


class DeploymentError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentStep:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DevicePlan:
    target: str
    device_id: str
    package: str
    device_type: str
    adapter: str
    release: str
    status: str
    steps: list[DeploymentStep]


def repo_root_from_common(common_dir: Path) -> Path:
    return common_dir.resolve().parents[1]


def _report_dir(repo_root: Path) -> Path:
    override = os.environ.get("HC_DEPLOY_REPORT_DIR")
    if override:
        return Path(override)
    return repo_root / "runtime" / "deployments"


def _verify_manifest_matches_inventory(entry: inventory_mod.DeviceInventoryEntry, manifest: manifest_mod.Manifest) -> None:
    if manifest.device_type != entry.device_type:
        raise DeploymentError(f"{entry.name}: manifest device type {manifest.device_type} does not match inventory {entry.device_type}")
    if manifest.package != entry.package:
        raise DeploymentError(f"{entry.name}: manifest package {manifest.package} does not match inventory {entry.package}")
    hardware = manifest.raw["hardware"]
    if entry.hardware_platform not in hardware["supported_platforms"]:
        raise DeploymentError(f"{entry.name}: unsupported platform {entry.hardware_platform}")
    if entry.operating_system not in hardware["supported_os"]:
        raise DeploymentError(f"{entry.name}: unsupported operating system {entry.operating_system}")
    if entry.architecture not in hardware["architectures"]:
        raise DeploymentError(f"{entry.name}: unsupported architecture {entry.architecture}")


def plan_deployment(
    *,
    repo_root: Path,
    release: str | None = None,
    target: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    config_root = repo_root / "06_config"
    manifests = manifest_mod.load_all_manifests(config_root)
    selected_release = release_mod.resolve_release(repo_root, release)
    deployment_id = f"hc-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    plans: list[DevicePlan] = []
    for entry in inventory_mod.select_inventory(target):
        manifest = manifests[entry.device_type]
        _verify_manifest_matches_inventory(entry, manifest)
        deployment = manifest.deployment
        steps = [
            DeploymentStep("validate_manifest", PASS, f"{manifest.path}"),
            DeploymentStep("validate_identity", PASS, f"device_id={entry.device_id}"),
            DeploymentStep("resolve_release", PASS, selected_release),
            DeploymentStep("backup", SKIPPED if dry_run else MANUAL, "planned; no live backup run by source-tree tests"),
            DeploymentStep("remote_apply", SKIPPED if dry_run else MANUAL, "remote execution is mocked until live adapters are approved"),
            DeploymentStep("verify", SKIPPED if dry_run else MANUAL, "target verification must run on hardware before deployment approval"),
        ]
        status = NO_CHANGE if dry_run else MANUAL
        plans.append(
            DevicePlan(
                target=entry.name,
                device_id=entry.device_id,
                package=entry.package,
                device_type=entry.device_type,
                adapter=str(deployment["adapter"]),
                release=selected_release,
                status=status,
                steps=steps,
            )
        )
    return {
        "deployment_id": deployment_id,
        "created_at": datetime.now(UTC).isoformat(),
        "release": selected_release,
        "dry_run": dry_run,
        "targets": [_plan_to_dict(plan) for plan in plans],
        "summary": {
            "total": len(plans),
            "status": NO_CHANGE if dry_run else MANUAL,
            "remote_execution": "mocked",
        },
    }


def _plan_to_dict(plan: DevicePlan) -> dict[str, Any]:
    data = asdict(plan)
    data["steps"] = [asdict(step) for step in plan.steps]
    return data


def write_report(repo_root: Path, report: dict[str, Any]) -> Path:
    directory = _report_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['deployment_id']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path
