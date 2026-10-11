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
transport = load_module("transport")
artifact = load_module("artifact")
adapters = load_module("adapters")
engine = load_module("engine")


class FakeRunner:
    def __init__(self, *, fail_contains: str | None = None, stdout_by_contains: dict[str, str] | None = None):
        self.commands = []
        self.fail_contains = fail_contains
        self.stdout_by_contains = stdout_by_contains or {}

    def __call__(self, command, *, input=None, timeout=None):
        self.commands.append(command)
        joined = " ".join(command)
        if self.fail_contains and self.fail_contains in joined:
            return transport.CommandResult(command, 255, "", "host key verification failed")
        for needle, stdout in self.stdout_by_contains.items():
            if needle in joined:
                return transport.CommandResult(command, 0, stdout, "")
        return transport.CommandResult(command, 0, "ok\n", "")


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
    assert report["summary"]["status"] == "PLANNED"
    assert {item["target"] for item in report["targets"]} == {"jetson", "conflict", "lab1"}
    assert all(step["status"] != "PASS" for item in report["targets"] for step in item["steps"] if step["name"] == "remote_identity")
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
    assert json.loads(status.stdout)["remote_execution"] == "not_contacted"

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


def test_ssh_transport_uses_existing_aliases_and_strict_host_keys(tmp_path):
    runner = FakeRunner()
    tx = transport.SSHTransport(runner=runner)
    tx.execute("jetson", "hostname")
    local = tmp_path / "artifact.tar.gz"
    local.write_text("artifact")
    tx.transfer_file("lab1", local, "/tmp/artifact.tar.gz")

    assert runner.commands[0][:7] == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "StrictHostKeyChecking=yes",
    ]
    assert "jetson" in runner.commands[0]
    assert runner.commands[1][0] == "scp"
    assert "lab1:/tmp/artifact.tar.gz" in runner.commands[1]


def test_ssh_transport_rejects_host_key_failures():
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="conflict"))
    with pytest.raises(transport.TransportError, match="host key verification failed"):
        tx.execute("conflict", "hostname")


def test_live_deploy_uses_single_artifact_and_stops_after_failed_transfer(tmp_path, monkeypatch):
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(tmp_path))

    fake_artifact = artifact.ReleaseArtifact(
        release="e" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(artifact, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="scp"))
    report = engine.deploy(
        repo_root=ROOT,
        release="e" * 40,
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["summary"]["status"] == "FAIL"
    assert report["targets"][0]["target"] == "jetson"
    assert report["targets"][0]["status"] == "FAIL"
    assert report["targets"][1]["status"] == "SKIPPED"
    assert report["targets"][2]["status"] == "SKIPPED"


def test_adapter_dry_run_includes_preservation_checks():
    fake_artifact = artifact.ReleaseArtifact(
        release="f" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="dry",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    by_name = inventory.inventory()
    conflict_steps = adapters.adapter_for(by_name["conflict"]).dry_run(fake_artifact).steps
    jetson_steps = adapters.adapter_for(by_name["jetson"]).dry_run(fake_artifact).steps
    lab_steps = adapters.adapter_for(by_name["lab1"]).dry_run(fake_artifact).steps

    assert any(step["name"] == "online_sqlite_backup" for step in conflict_steps)
    assert any(step["name"] == "preflight_docker_layout" for step in jetson_steps)
    assert any(step["name"] == "preflight_lab1_safety" for step in lab_steps)
    assert all(step["status"] == "PLANNED" for step in jetson_steps)


def test_rollback_steps_are_adapter_specific():
    by_name = inventory.inventory()

    jetson = adapters.adapter_for(by_name["jetson"]).rollback_steps()
    conflict = adapters.adapter_for(by_name["conflict"]).rollback_steps()
    lab1 = adapters.adapter_for(by_name["lab1"]).rollback_steps()

    assert any(step.name == "restore_previous_container" for step in jetson)
    assert any(step.name == "rollback_heartbeat" for step in conflict)
    assert any(step.name == "restore_role_helper" for step in lab1)


def test_live_deploy_skips_target_already_at_release(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="1" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(
        runner=FakeRunner(stdout_by_contains={"cat /etc/hcm/homecontrol-release": "1" * 40 + "\n"})
    )

    report = engine.deploy(
        repo_root=ROOT,
        release="1" * 40,
        target="jetson",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["targets"][0]["status"] == "NO CHANGE"
    assert all("docker build" not in " ".join(cmd) for cmd in tx.runner.commands)


def test_no_change_is_success_and_fleet_continues(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="2" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(
        runner=FakeRunner(stdout_by_contains={"cat /etc/hcm/homecontrol-release": "2" * 40 + "\n"})
    )

    report = engine.deploy(repo_root=ROOT, release="2" * 40, dry_run=False, transport=tx, run_tests=False)

    assert report["summary"]["status"] == "PASS"
    assert [item["status"] for item in report["targets"]][0] == "NO CHANGE"
    assert {item["target"] for item in report["targets"]} == {"jetson", "lab1", "conflict"}


def test_changed_failure_attempts_safe_rollback(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="3" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(
        runner=FakeRunner(fail_contains="tee /opt/homecontrol-lab/state/homecontrol-release")
    )

    report = engine.deploy(
        repo_root=ROOT,
        release="3" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["targets"][0]["status"] == "ROLLED BACK"
    assert any(step.get("rollback") for step in report["targets"][0]["steps"])


def test_preflight_reports_facts_and_blockers():
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="module.json"))

    report = engine.preflight(repo_root=ROOT, target="lab1", transport=tx)

    assert report["summary"]["status"] == "FAIL"
    assert report["targets"][0]["blockers"]
    assert report["targets"][0]["assumptions"]


def test_cli_exit_code_helper_flags_failed_reports():
    spec = importlib.util.spec_from_file_location("homecontrol_cli_for_exit_test", ROOT / "homecontrol_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["homecontrol_cli_for_exit_test"] = module
    spec.loader.exec_module(module)

    assert module._exit_for_report({"summary": {"status": "FAIL"}}) == 1
    assert module._exit_for_report({"summary": {"status": "PASS"}}) == 0
    assert module._exit_for_report({"summary": {"status": "NO CHANGE"}}) == 0
