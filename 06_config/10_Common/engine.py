from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from . import adapters as adapters_mod
    from . import artifact as artifact_mod
    from . import inventory as inventory_mod
    from . import manifest as manifest_mod
    from . import release as release_mod
    from . import transport as transport_mod
except ImportError:  # Allows direct loading from homecontrol_cli.py.
    import adapters as adapters_mod  # type: ignore
    import artifact as artifact_mod  # type: ignore
    import inventory as inventory_mod  # type: ignore
    import manifest as manifest_mod  # type: ignore
    import release as release_mod  # type: ignore
    import transport as transport_mod  # type: ignore


PASS = "PASS"
SKIPPED = "SKIPPED"
NO_CHANGE = "NO CHANGE"
PLANNED = "PLANNED"
ROLLED_BACK = "ROLLED BACK"
MANUAL = "MANUAL INTERVENTION REQUIRED"
FAIL = "FAIL"
SUCCESS_STATUSES = {PASS, NO_CHANGE, ROLLED_BACK}


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
    entries = ordered_inventory(inventory_mod.select_inventory(target))
    fake_artifact = artifact_mod.ReleaseArtifact(
        release=selected_release,
        path=Path(f"/tmp/homecontrol-{selected_release}.tar.gz"),
        sha256="dry-run",
        metadata_path=Path(f"/tmp/homecontrol-{selected_release}.json"),
    )
    for entry in entries:
        manifest = manifests[entry.device_type]
        _verify_manifest_matches_inventory(entry, manifest)
        deployment = manifest.deployment
        adapter_result = adapters_mod.adapter_for(entry).dry_run(fake_artifact)
        steps = [
            DeploymentStep("validate_manifest", PASS, f"{manifest.path}"),
            DeploymentStep("validate_identity", PASS, f"device_id={entry.device_id}"),
            DeploymentStep("resolve_release", PASS, selected_release),
        ]
        steps.extend(
            DeploymentStep(
                step["name"],
                PLANNED if dry_run else MANUAL,
                step["detail"],
            )
            for step in adapter_result.steps
        )
        status = PLANNED if dry_run else MANUAL
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
            "status": PLANNED if dry_run else MANUAL,
            "remote_execution": "disabled" if dry_run else "requires_explicit_transport",
        },
    }


def ordered_inventory(entries: list[inventory_mod.DeviceInventoryEntry]) -> list[inventory_mod.DeviceInventoryEntry]:
    order = {"HCM": 10, "LAB": 20, "CONFLICT": 30}
    return sorted(entries, key=lambda item: order.get(item.device_type, 50))


def run_repository_tests(repo_root: Path) -> None:
    result = subprocess.run(
        [str(repo_root / ".venv" / "bin" / "python"), "-m", "pytest", "-q"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("repository tests failed before deployment\n" + result.stdout + result.stderr)


def deploy(
    *,
    repo_root: Path,
    release: str | None = None,
    target: str | None = None,
    dry_run: bool = True,
    transport: transport_mod.SSHTransport | None = None,
    run_tests: bool = True,
) -> dict[str, Any]:
    if dry_run:
        return plan_deployment(repo_root=repo_root, release=release, target=target, dry_run=True)

    config_root = repo_root / "06_config"
    manifests = manifest_mod.load_all_manifests(config_root)
    selected_release = release_mod.resolve_release(repo_root, release)
    if run_tests:
        run_repository_tests(repo_root)
    transport = transport or transport_mod.SSHTransport()
    deployment_id = f"hc-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    entries = ordered_inventory(inventory_mod.select_inventory(target))
    targets: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="homecontrol-release-") as tmp:
        artifact = artifact_mod.create_release_artifact(repo_root, selected_release, Path(tmp))
        failed = False
        for entry in entries:
            manifest = manifests[entry.device_type]
            _verify_manifest_matches_inventory(entry, manifest)
            if failed:
                targets.append(
                    {
                        "target": entry.name,
                        "device_id": entry.device_id,
                        "package": entry.package,
                        "device_type": entry.device_type,
                        "adapter": entry.live_adapter,
                        "release": selected_release,
                        "status": SKIPPED,
                        "steps": [{"name": "dependency_order", "status": SKIPPED, "detail": "prior target failed"}],
                    }
                )
                continue
            result = adapters_mod.adapter_for(entry).apply(transport, artifact)
            if result.status not in SUCCESS_STATUSES:
                failed = True
            targets.append(
                {
                    "target": entry.name,
                    "device_id": entry.device_id,
                    "package": entry.package,
                    "device_type": entry.device_type,
                    "adapter": entry.live_adapter,
                    "release": selected_release,
                    "status": result.status,
                    "steps": result.steps,
                    "artifact_sha256": artifact.sha256,
                }
            )

    status = FAIL if any(item["status"] == FAIL for item in targets) else PASS
    return {
        "deployment_id": deployment_id,
        "created_at": datetime.now(UTC).isoformat(),
        "release": selected_release,
        "dry_run": False,
        "targets": targets,
        "summary": {
            "total": len(targets),
            "status": status,
            "remote_execution": "ssh",
        },
    }


def verify(
    *,
    repo_root: Path,
    target: str | None = None,
    transport: transport_mod.SSHTransport | None = None,
) -> dict[str, Any]:
    selected = ordered_inventory(inventory_mod.select_inventory(target))
    transport = transport or transport_mod.SSHTransport()
    results = []
    for entry in selected:
        try:
            result = transport.execute(entry.ssh_alias, "hostname && uname -a", timeout=20)
        except Exception as exc:
            results.append({"target": entry.name, "status": FAIL, "detail": str(exc)})
        else:
            results.append({"target": entry.name, "status": PASS, "detail": result.stdout.strip()})
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "verification_scope": "read-only ssh connectivity",
        "targets": results,
        "summary": {"status": FAIL if any(item["status"] == FAIL for item in results) else PASS},
    }


def preflight(
    *,
    repo_root: Path,
    target: str | None = None,
    transport: transport_mod.SSHTransport | None = None,
) -> dict[str, Any]:
    manifests = manifest_mod.load_all_manifests(repo_root / "06_config")
    selected = ordered_inventory(inventory_mod.select_inventory(target))
    transport = transport or transport_mod.SSHTransport()
    results = []
    for entry in selected:
        _verify_manifest_matches_inventory(entry, manifests[entry.device_type])
        result = adapters_mod.adapter_for(entry).preflight(transport)
        blockers = [step for step in result.steps if step["status"] == FAIL]
        assumptions = [
            "No files are transferred.",
            "No services are restarted.",
            "Compatibility is based on read-only command output.",
        ]
        results.append(
            {
                "target": entry.name,
                "device_id": entry.device_id,
                "package": entry.package,
                "status": result.status,
                "facts": result.steps,
                "blockers": blockers,
                "assumptions": assumptions,
            }
        )
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "preflight_scope": "read-only remote layout compatibility",
        "targets": results,
        "summary": {"status": FAIL if any(item["status"] == FAIL for item in results) else PASS},
    }


def rollback(
    *,
    repo_root: Path,
    target: str,
    transport: transport_mod.SSHTransport | None = None,
) -> dict[str, Any]:
    manifests = manifest_mod.load_all_manifests(repo_root / "06_config")
    entry = inventory_mod.select_inventory(target)[0]
    _verify_manifest_matches_inventory(entry, manifests[entry.device_type])
    transport = transport or transport_mod.SSHTransport()
    result = adapters_mod.adapter_for(entry).rollback(transport)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "target": target,
        "status": result.status,
        "steps": result.steps,
        "summary": {
            "status": result.status,
            "rollback_scope": "adapter-specific application rollback",
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
