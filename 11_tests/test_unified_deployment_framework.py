import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "06_config" / "10_Common"


def load_module(name: str):
    path = COMMON / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manifest = load_module("manifest")
inventory = load_module("inventory")
release = load_module("release")
engine = load_module("engine")


def test_all_device_manifests_validate_and_rmc_is_firmware_only():
    manifests = manifest.load_all_manifests(ROOT / "06_config")

    assert set(manifests) == {"HCM", "SIM", "LCM", "RCM", "PNL", "RMC", "CONFLICT", "LAB"}
    assert manifests["RMC"].deployment["adapter"] == "firmware"
    assert "install" not in manifests["RMC"].deployment
    assert manifests["HCM"].deployment["adapter"] == "hcm_docker"


def test_manifest_rejects_unsafe_paths_and_unknown_device_type(tmp_path):
    raw = yaml.safe_load((ROOT / "06_config" / "04_RCM" / "manifest.yaml").read_text())
    raw["device_type"] = "ROOT"

    with pytest.raises(manifest.ManifestError, match="unsupported device_type"):
        manifest.validate_manifest(raw, path=tmp_path / "04_RCM" / "manifest.yaml")

    raw = yaml.safe_load((ROOT / "06_config" / "04_RCM" / "manifest.yaml").read_text())
    raw["configuration_files"].append("../secret")
    with pytest.raises(manifest.ManifestError, match="simple relative"):
        manifest.validate_manifest(raw, path=tmp_path / "04_RCM" / "manifest.yaml")


def test_inventory_package_selection_preserves_lab1_identity_independent_of_role():
    assert inventory.package_for_device("RCM", device_id="2c:cf:67:5d:34:14") == "08_LAB"
    assert inventory.package_for_device("LCM", device_id="2ccf675d3414") == "08_LAB"
    assert inventory.package_for_device("RCM", device_id="001122334455") == "04_RCM"


def test_hcm_commissioning_plan_uses_shared_package_selection():
    spec = importlib.util.spec_from_file_location(
        "deployment_selection",
        ROOT / "01_HCM" / "deployment_selection.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["deployment_selection"] = module
    spec.loader.exec_module(module)

    plan = module.commissioning_plan("RCM", device_id="2ccf675d3414", hardware_platform="raspberry_pi_4")
    assert plan["deployment_package"] == "08_LAB"
    assert plan["status"] == "pending_admin_approval"


def test_release_requires_full_sha():
    assert release.validate_release_sha("a" * 40) == "a" * 40
    with pytest.raises(release.ReleaseError):
        release.validate_release_sha("main")
    with pytest.raises(release.ReleaseError):
        release.validate_release_sha("abc123")


def test_deployment_plan_is_dry_run_noop_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(tmp_path))
    report = engine.plan_deployment(repo_root=ROOT, release="b" * 40, dry_run=True)
    path = engine.write_report(ROOT, report)

    assert report["release"] == "b" * 40
    assert report["summary"]["status"] == "NO CHANGE"
    assert {item["target"] for item in report["targets"]} == {"jetson", "conflict", "lab1"}
    assert json.loads(path.read_text())["deployment_id"] == report["deployment_id"]


def test_deployment_plan_rejects_incompatible_inventory(monkeypatch):
    bad = inventory.DeviceInventoryEntry(
        name="bad-lab",
        ssh_alias="bad-lab",
        ip_address="192.0.2.1",
        device_id="001122334455",
        device_type="LAB",
        package="08_LAB",
        hardware_platform="jetson_xavier_nx",
        architecture="aarch64",
        operating_system="debian",
        live_adapter="lab1_simulation",
    )

    monkeypatch.setattr(inventory, "select_inventory", lambda target=None: [bad])
    with pytest.raises(engine.DeploymentError, match="unsupported platform"):
        engine.plan_deployment(repo_root=ROOT, release="c" * 40)


def test_homecontrol_cli_status_inventory_and_dry_run(tmp_path):
    env = os.environ.copy()
    env["HC_DEPLOY_REPORT_DIR"] = str(tmp_path)

    status = subprocess.run(
        [sys.executable, "-m", "homecontrol_cli", "status"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["remote_execution"] == "mocked"

    deploy = subprocess.run(
        [sys.executable, "-m", "homecontrol_cli", "deploy", "--dry-run", "--release", "d" * 40],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert deploy.returncode == 0, deploy.stderr
    data = json.loads(deploy.stdout)
    assert data["dry_run"] is True
    assert Path(data["report_path"]).exists()
