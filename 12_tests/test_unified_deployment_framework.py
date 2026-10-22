from types import SimpleNamespace
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "07_config" / "10_Common"


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


def load_script_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sample_heartbeat_config():
    return {
        "authorized_devices": [
            {"device_id": "48b02d87db16", "hostname": "jetson", "ip_address": "192.168.20.27"},
            {"device_id": "2ccf675d3414", "hostname": "lab1", "ip_address": "192.168.20.36"},
        ]
    }


def sample_heartbeat_status():
    return {
        "status": {
            "registry": {
                "48b02d87db16": {
                    "hostname": "jetson",
                    "ip_address": "192.168.20.27",
                    "authorized": True,
                    "maintenance": False,
                    "active_fault": None,
                },
                "2ccf675d3414": {
                    "hostname": "lab1",
                    "ip_address": "192.168.20.36",
                    "authorized": True,
                    "maintenance": False,
                    "active_fault": None,
                },
            }
        }
    }


def test_all_device_manifests_validate_and_rmc_is_firmware_only():
    manifests = manifest.load_all_manifests(ROOT / "07_config")

    assert set(manifests) == {"HCM", "SIM", "LCM", "RCM", "PNL", "RMC", "CONFLICT", "LAB"}
    assert manifests["RMC"].deployment["adapter"] == "firmware"
    assert "install" not in manifests["RMC"].deployment
    assert manifests["HCM"].deployment["adapter"] == "hcm_docker"


def test_manifest_rejects_unsafe_paths_and_unknown_device_type(tmp_path):
    raw = yaml.safe_load((ROOT / "07_config" / "04_RCM" / "manifest.yaml").read_text())
    raw["device_type"] = "ROOT"

    with pytest.raises(manifest.ManifestError, match="unsupported device_type"):
        manifest.validate_manifest(raw, path=tmp_path / "04_RCM" / "manifest.yaml")

    raw = yaml.safe_load((ROOT / "07_config" / "04_RCM" / "manifest.yaml").read_text())
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


def test_homecontrol_cli_rejects_bare_live_deploy_and_all_is_explicit(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("homecontrol_cli_for_deploy_gate", ROOT / "homecontrol_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["homecontrol_cli_for_deploy_gate"] = module
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc:
        module.main(["deploy", "--yes", "--skip-tests", "--release", "a" * 40])
    assert exc.value.code == 2

    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(
        module.engine,
        "deploy",
        lambda **kwargs: {
            "deployment_id": "test-deploy",
            "summary": {"status": "PASS"},
            "targets": [{"target": "lab1", "status": "PASS"}],
        },
    )
    assert module.main(["deploy", "--all", "--yes", "--skip-tests", "--release", "a" * 40]) == 0


def test_homecontrol_cli_rejects_target_and_all_together():
    spec = importlib.util.spec_from_file_location("homecontrol_cli_for_target_gate", ROOT / "homecontrol_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["homecontrol_cli_for_target_gate"] = module
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc:
        module.main(["deploy", "--target", "lab1", "--all", "--yes", "--release", "a" * 40])
    assert exc.value.code == 2


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


def test_ssh_transport_filters_noninteractive_warnings_but_preserves_real_failure():
    class WarningRunner:
        def __call__(self, command, *, input=None, timeout=None):
            return transport.CommandResult(command, 7, "useful stdout\n", "tput: No value for $TERM and no -T specified\nactual failure\n")

    tx = transport.SSHTransport(runner=WarningRunner())
    with pytest.raises(transport.TransportError) as exc:
        tx.execute("conflict", "false", step_name="heartbeat_auth_config")
    text = str(exc.value)
    assert "target=conflict" in text
    assert "step=heartbeat_auth_config" in text
    assert "exit=7" in text
    assert "actual failure" in text
    assert "tput" not in text


def test_ssh_transport_ignores_post_quantum_warning_on_success():
    class WarningRunner:
        def __call__(self, command, *, input=None, timeout=None):
            return transport.CommandResult(command, 0, "ok\n", "Warning: post-quantum algorithm unavailable\n")

    tx = transport.SSHTransport(runner=WarningRunner())
    result = tx.execute("jetson", "true")
    assert result.stdout == "ok"
    assert "post-quantum" not in result.stderr.lower()


def test_read_only_ssh_retries_transient_banner_timeout():
    class FlakyRunner:
        def __init__(self):
            self.calls = 0
            self.commands = []

        def __call__(self, command, *, input=None, timeout=None):
            self.calls += 1
            self.commands.append(command)
            if self.calls == 1:
                return transport.CommandResult(command, 255, "", "Connection timed out during banner exchange")
            return transport.CommandResult(command, 0, "ok\n", "")

    runner = FlakyRunner()
    tx = transport.SSHTransport(runner=runner, read_only_retries=2)

    result = tx.execute("jetson", "hostname", read_only=True)

    assert result.stdout == "ok"
    assert runner.calls == 2


def test_state_changing_ssh_does_not_retry_transient_failure():
    class FlakyRunner:
        def __init__(self):
            self.calls = 0

        def __call__(self, command, *, input=None, timeout=None):
            self.calls += 1
            return transport.CommandResult(command, 255, "", "Connection timed out during banner exchange")

    runner = FlakyRunner()
    tx = transport.SSHTransport(runner=runner, read_only_retries=2)

    with pytest.raises(transport.TransportError, match="banner exchange"):
        tx.execute("jetson", "sudo systemctl restart hcm.service", read_only=False)

    assert runner.calls == 1


def test_proxyjump_timeout_is_retryable_but_host_key_failure_is_not():
    class ProxyRunner:
        def __init__(self):
            self.calls = 0

        def __call__(self, command, *, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return transport.CommandResult(command, 255, "", "ProxyJump connection timed out")
            return transport.CommandResult(command, 0, "ok\n", "")

    proxy = ProxyRunner()
    transport.SSHTransport(runner=proxy).execute("jetson", "hostname", read_only=True)
    assert proxy.calls == 2

    runner = FakeRunner(fail_contains="conflict")
    tx = transport.SSHTransport(runner=runner)
    with pytest.raises(transport.TransportError, match="host key verification failed"):
        tx.execute("conflict", "hostname", read_only=True)
    assert len(runner.commands) == 1


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
        explicit_all=True,
        transport=tx,
        run_tests=False,
    )

    assert report["summary"]["status"] == "FAIL"
    assert report["targets"][0]["target"] == "jetson"
    assert report["targets"][0]["status"] == "FAIL"
    assert report["targets"][1]["status"] == "SKIPPED"
    assert report["targets"][2]["status"] == "SKIPPED"


def test_single_target_live_deploy_only_contacts_selected_device(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="6" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(runner=FakeRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="6" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["summary"]["status"] == "PASS"
    assert [item["target"] for item in report["targets"]] == ["lab1"]
    joined = [" ".join(command) for command in tx.runner.commands]
    assert all(" lab1 " in command or "lab1:" in command for command in joined)
    assert all("jetson" not in command and "conflict" not in command for command in tx.runner.commands)


def test_engine_rejects_bare_live_fleet_deploy():
    with pytest.raises(engine.DeploymentError, match="explicit target"):
        engine.deploy(repo_root=ROOT, release="7" * 40, dry_run=False, run_tests=False)


def test_single_target_dry_run_and_target_verify_scope():
    report = engine.plan_deployment(repo_root=ROOT, release="8" * 40, target="lab1", dry_run=True)

    assert report["fleet_scope"] == "single-target"
    assert [item["target"] for item in report["targets"]] == ["lab1"]

    tx = transport.SSHTransport(runner=FakeRunner())
    verify_report = engine.verify(repo_root=ROOT, target="lab1", transport=tx)
    assert [item["target"] for item in verify_report["targets"]] == ["lab1"]


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

    assert any(step["name"] == "backup_heartbeat_app" for step in conflict_steps)
    assert any(step["name"] == "preflight_docker_layout" for step in jetson_steps)
    assert any(step["name"] == "preflight_lab1_safety" for step in lab_steps)
    assert all(step["status"] == "PLANNED" for step in jetson_steps)


def test_jetson_preflight_does_not_require_env_file_or_pipe_docker_json_to_heredoc():
    command = adapters.adapter_for(inventory.inventory()["jetson"])._docker_preflight_command()
    assert "/etc/hcm/hcm.env" not in command
    assert "docker inspect hcm-test | python3 - <<'PY'" not in command
    assert "subprocess.Popen(['docker','inspect',name]" in command
    assert "text=True" not in command
    assert "capture_output" not in command
    assert "/srv/hcm-data/postgres" in command
    assert "/run/secrets/postgres_password" in command


def test_live_hcm_image_installs_git_and_deployment_smoke_tests_it_before_replace():
    dockerfile = (ROOT / "07_config" / "01_HCM" / "Dockerfile.live").read_text()
    assert "apt-get install -y --no-install-recommends git ca-certificates" in dockerfile

    fake_artifact = artifact.ReleaseArtifact(
        release="a" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    steps = adapters.adapter_for(inventory.inventory()["jetson"]).steps(fake_artifact, deployment_id="hc-git-test")
    names = [step.name for step in steps]
    smoke = next(step.command for step in steps if step.name == "verify_hcm_image_git")

    assert "docker run --rm --user 10001:10001" in smoke
    assert "git --version" in smoke
    assert names.index("verify_hcm_image_git") < names.index("replace_hcm_container")


def test_jetson_health_discovers_published_non_loopback_endpoint():
    command = adapters.adapter_for(inventory.inventory()["jetson"])._hcm_health_command()

    assert "PortBindings" in command
    assert "8080/tcp" in command
    assert "api/v1/health" in command
    assert "127.0.0.1:8080" not in command
    assert "0.0.0.0" in command


def test_conflict_preflight_uses_sudo_noninteractive_and_safe_metadata():
    steps = adapters.adapter_for(inventory.inventory()["conflict"]).preflight_steps()
    commands = "\n".join(step.command for step in steps)
    assert "sudo -n" in commands
    assert "heartbeat_auth_secret_file" in commands
    assert "print('auth_mode=hmac-sha256 secret_present=true" in commands
    assert "cat /etc/hcm-heartbeat/config.json" not in commands
    service = next(step.command for step in steps if step.name == "heartbeat_service")
    assert "bind_address" in service
    assert "advertise_ip" in service
    assert "127.0.0.1:6004" not in service


def test_conflict_verify_command_uses_python_status_verifier_without_pipe_heredoc():
    command = adapters.adapter_for(inventory.inventory()["conflict"])._heartbeat_verify_command(script="/tmp/release/11_scripts/heartbeat_verify_readonly.sh")

    assert "heartbeat_status_verify.py" in command
    assert "urllib" not in command
    assert "| python3 - <<'PY'" not in command
    assert 'curl -fsS "$endpoint/status"' not in command


def test_conflict_adapter_uses_deployment_specific_backup_and_restores_marker():
    fake_artifact = artifact.ReleaseArtifact(
        release="e" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    adapter = adapters.adapter_for(inventory.inventory()["conflict"])
    steps = adapter.steps(fake_artifact, deployment_id="hc-20261012T010203Z-test")
    backup = next(step.command for step in steps if step.name == "backup_heartbeat_app")
    names = [step.name for step in steps]

    assert "/var/backups/homecontrol-heartbeat/app-rollback-hc-20261012T010203Z-test" in backup
    assert "app-rollback-" + "e" * 40 not in backup
    assert "HC_HEARTBEAT_RELEASE_MARKER" in backup
    assert "homecontrol-release.absent" in backup
    assert "registry_snapshot=disaster_recovery_only" in backup
    assert names.index("verify_heartbeat") < names.index("record_release")

    rollback = adapter.rollback_after_failure(
        transport.SSHTransport(runner=FakeRunner()),
        fake_artifact,
        deployment_id="hc-20261012T010203Z-test",
    )
    restore = next(step["detail"] for step in rollback.steps if step["name"] == "rollback_heartbeat_app")
    assert "/var/backups/homecontrol-heartbeat/app-rollback-hc-20261012T010203Z-test" in restore
    assert "marker_restored=true" in restore
    assert "registry_preserved=true" in restore
    assert "registry.sqlite3" not in restore
    assert "/etc/hcm-heartbeat/config.json" not in restore


def test_conflict_safety_gate_checks_backup_collision_storage_and_registry_readonly():
    adapter = adapters.adapter_for(inventory.inventory()["conflict"])
    fake_artifact = artifact.ReleaseArtifact(
        release="e" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    steps = adapter.safety_gate_steps(fake_artifact, "hc-collision-test")
    commands = "\n".join(step.command for step in steps)

    assert "app-rollback-hc-collision-test" in commands
    assert "! sudo -n test -e" in commands
    assert "df -Pk /var/backups" in commands
    assert "PRAGMA integrity_check" in commands
    assert "mkdir" not in commands
    assert "heartbeat_backup.sh" not in commands


def test_heartbeat_status_verifier_accepts_valid_registered_authorized_devices():
    module = load_script_module("heartbeat_status_verify_test", "11_scripts/heartbeat_status_verify.py")

    result = module.verify_status_payload(sample_heartbeat_status(), sample_heartbeat_config())

    assert result["registered"] == ["48b02d87db16", "2ccf675d3414"]
    assert result["active_faults"] == "none"


def test_heartbeat_status_verifier_rejects_missing_registered_or_authorized_devices():
    module = load_script_module("heartbeat_status_verify_missing_test", "11_scripts/heartbeat_status_verify.py")
    status = sample_heartbeat_status()
    del status["status"]["registry"]["2ccf675d3414"]

    with pytest.raises(module.HeartbeatStatusError, match="missing registered devices"):
        module.verify_status_payload(status, sample_heartbeat_config())

    cfg = sample_heartbeat_config()
    cfg["authorized_devices"] = cfg["authorized_devices"][:1]
    with pytest.raises(module.HeartbeatStatusError, match="missing authorized config entries"):
        module.verify_status_payload(sample_heartbeat_status(), cfg)


def test_heartbeat_status_verifier_rejects_active_faults_and_bad_identity():
    module = load_script_module("heartbeat_status_verify_fault_test", "11_scripts/heartbeat_status_verify.py")
    status = sample_heartbeat_status()
    status["status"]["registry"]["48b02d87db16"]["active_fault"] = {"code": "communication_loss"}

    with pytest.raises(module.HeartbeatStatusError, match="active_fault communication_loss"):
        module.verify_status_payload(status, sample_heartbeat_config())

    status = sample_heartbeat_status()
    status["status"]["registry"]["2ccf675d3414"]["hostname"] = "wrong"
    with pytest.raises(module.HeartbeatStatusError, match="hostname wrong != lab1"):
        module.verify_status_payload(status, sample_heartbeat_config())


def test_heartbeat_status_verifier_rejects_invalid_status_json(monkeypatch):
    module = load_script_module("heartbeat_status_verify_invalid_json_test", "11_scripts/heartbeat_status_verify.py")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b"not-json"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda url, timeout=None: FakeResponse())

    with pytest.raises(module.HeartbeatStatusError, match="invalid status JSON"):
        module.fetch_status("http://192.0.2.1:6004", 1)


def test_lab1_layout_preflight_uses_python_hostname_and_file_checks():
    steps = adapters.adapter_for(inventory.inventory()["lab1"]).preflight_steps()
    layout = next(step.command for step in steps if step.name == "lab1_agent_layout")
    assert "socket.gethostname().split('.')[0] == 'lab1'" in layout
    assert "/opt/homecontrol-lab/lab_agent.py" in layout
    assert "/opt/homecontrol-lab/state/module.json" in layout


def test_lab1_service_check_reports_individual_service_status_without_socket_requirement():
    steps = adapters.adapter_for(inventory.inventory()["lab1"]).preflight_steps()
    command = next(step.command for step in steps if step.name == "lab1_services")

    assert "homecontrol-lab.service" in command
    assert "hcm-heartbeat.service" in command
    assert "SubState" in command
    assert "heartbeat_control_socket" in command
    assert "test -S /run/hcm-heartbeat/control.sock" not in command


def test_lab1_heartbeat_socket_is_optional_but_conflict_destination_is_checked():
    steps = adapters.adapter_for(inventory.inventory()["lab1"]).preflight_steps()
    heartbeat = next(step.command for step in steps if step.name == "lab1_heartbeat_client")

    assert "control_socket=optional" in heartbeat
    assert "conflict_address" in heartbeat
    assert "socket.create_connection" in heartbeat
    assert "/status" in heartbeat
    assert "peer_online=true" in heartbeat
    assert "heartbeat_auth_secret_file" not in heartbeat


def test_lab1_state_safety_command_enforces_identity_and_simulation_lockout():
    command = adapters.adapter_for(inventory.inventory()["lab1"])._lab_state_safety_command("/opt/homecontrol-lab/backups/hc-test")

    assert "module_state_invalid" in command
    assert "hostname {} != lab1" in command
    assert "device_id {} != 2ccf675d3414" in command
    assert "state hostname {} != lab1" in command
    assert "simulation is not true" in command
    assert "physical_outputs_enabled is not false" in command
    assert "role missing" in command
    assert "for key in ('role','device_id','hostname','simulation','physical_outputs_enabled')" in command
    assert "backup_module_state_invalid" in command


def test_lab1_post_install_verifies_safety_services_and_heartbeat_before_marker():
    fake_artifact = artifact.ReleaseArtifact(
        release="a" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    names = [step.name for step in adapters.adapter_for(inventory.inventory()["lab1"]).steps(fake_artifact, deployment_id="hc-test")]

    assert names.index("restart_lab_agent") < names.index("verify_lab_state_safety")
    assert names.index("verify_lab_state_safety") < names.index("verify_lab_services")
    assert names.index("verify_lab_services") < names.index("verify_lab_heartbeat_client")
    assert names.index("verify_lab_heartbeat_client") < names.index("record_release")
    assert names.index("backup_lab_agent_components") < names.index("stage_module_source")
    assert names.index("stage_module_source") < names.index("install_reconnect_snapshot")
    assert names.index("install_reconnect_snapshot") < names.index("restart_lab_agent")
    assert names.index("verify_reconnect_snapshot") < names.index("record_release")


def test_lab1_deployment_uses_release_specific_backup_and_restores_marker():
    fake_artifact = artifact.ReleaseArtifact(
        release="9" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    adapter = adapters.adapter_for(inventory.inventory()["lab1"])
    steps = adapter.steps(fake_artifact, deployment_id="hc-test-123")
    backup = next(step.command for step in steps if step.name == "backup_lab_agent_components")
    rollback = adapter.rollback_after_failure(
        transport.SSHTransport(runner=FakeRunner()),
        fake_artifact,
        deployment_id="hc-test-123",
    )
    restore = next(step["detail"] for step in rollback.steps if step["name"] == "restore_role_helper")

    assert "/opt/homecontrol-lab/backups/hc-test-123" in backup
    assert "cp -a /opt/homecontrol-lab/lab1_role_agent.py" in backup
    assert "cp -a /opt/homecontrol-lab/state/module.json" in backup
    assert "homecontrol-release.absent" in backup
    assert "cmp -s" in backup
    assert "/opt/homecontrol-lab/backups/hc-test-123" in restore
    assert "marker_restored=true" in restore


def test_rollback_steps_are_adapter_specific():
    by_name = inventory.inventory()

    jetson = adapters.adapter_for(by_name["jetson"]).rollback_steps()
    conflict = adapters.adapter_for(by_name["conflict"]).rollback_steps()
    lab1 = adapters.adapter_for(by_name["lab1"]).rollback_steps()

    assert any(step.name == "restore_previous_container" for step in jetson)
    assert any(step.name == "rollback_heartbeat_app" for step in conflict)
    assert any(step.name == "restore_role_helper" for step in lab1)
    assert all("registry.sqlite3" not in step.command for step in conflict)


def write_deployment_report(report_dir: Path, *, deployment_id: str, target: str, release: str, recovery_step: str, recovery_status: str = "PASS", duplicate: bool = False):
    target_record = {
        "target": target,
        "release": release,
        "status": "PASS",
        "steps": [{"name": recovery_step, "status": recovery_status, "detail": "ok"}],
    }
    targets = [target_record]
    if duplicate:
        targets.append(dict(target_record))
    report = {
        "deployment_id": deployment_id,
        "release": release,
        "dry_run": False,
        "targets": targets,
        "summary": {"status": "PASS"},
    }
    report_dir.mkdir(parents=True)
    (report_dir / f"{deployment_id}.json").write_text(json.dumps(report))
    return report


def test_manual_jetson_rollback_uses_deployment_specific_container_from_report(tmp_path, monkeypatch):
    deployment_id = "hc-20261012T030000Z-abc12345"
    release_sha = "a" * 40
    report_dir = tmp_path / "reports"
    write_deployment_report(report_dir, deployment_id=deployment_id, target="jetson", release=release_sha, recovery_step="replace_hcm_container")
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(report_dir))
    tx = transport.SSHTransport(runner=FakeRunner())

    report = engine.rollback(repo_root=ROOT, target="jetson", deployment_id=deployment_id, transport=tx)

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["status"] == "PASS"
    assert report["rollback_release"] == release_sha
    assert any("--rollback-name hcm-rollback-hc-20261012T030000Z-abc12345" in command for command in joined)
    assert all("hcm-rollback-manual" not in command for command in joined)
    assert any(f"/tmp/homecontrol-release-{release_sha}/11_scripts/hcm_docker_deploy.py" in command for command in joined)


def test_manual_conflict_rollback_uses_deployment_specific_backup_from_report(tmp_path, monkeypatch):
    deployment_id = "hc-20261012T031500Z-def67890"
    release_sha = "b" * 40
    report_dir = tmp_path / "reports"
    write_deployment_report(report_dir, deployment_id=deployment_id, target="conflict", release=release_sha, recovery_step="backup_heartbeat_app")
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(report_dir))
    tx = transport.SSHTransport(runner=FakeRunner())

    report = engine.rollback(repo_root=ROOT, target="conflict", deployment_id=deployment_id, transport=tx)

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["status"] == "PASS"
    assert any("/var/backups/homecontrol-heartbeat/app-rollback-hc-20261012T031500Z-def67890" in command for command in joined)
    assert all("/var/backups/homecontrol-heartbeat/homecontrol-deploy-rollback" not in command for command in joined)
    assert any(f"/tmp/homecontrol-release-{release_sha}/11_scripts/heartbeat_verify_readonly.sh" in command for command in joined)


def test_manual_rollback_rejects_missing_or_ambiguous_deployment_records_without_mutation(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(report_dir))
    tx = transport.SSHTransport(runner=FakeRunner())

    with pytest.raises(engine.RollbackResolutionError, match="missing"):
        engine.rollback(repo_root=ROOT, target="jetson", deployment_id="hc-missing", transport=tx)
    assert tx.runner.commands == []

    write_deployment_report(
        report_dir,
        deployment_id="hc-ambiguous",
        target="jetson",
        release="c" * 40,
        recovery_step="replace_hcm_container",
        duplicate=True,
    )
    with pytest.raises(engine.RollbackResolutionError, match="ambiguous"):
        engine.rollback(repo_root=ROOT, target="jetson", deployment_id="hc-ambiguous", transport=tx)
    assert tx.runner.commands == []


def test_manual_rollback_rejects_unverified_recovery_step_without_mutation(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports"
    write_deployment_report(
        report_dir,
        deployment_id="hc-no-recovery",
        target="conflict",
        release="d" * 40,
        recovery_step="backup_heartbeat_app",
        recovery_status="FAIL",
    )
    monkeypatch.setenv("HC_DEPLOY_REPORT_DIR", str(report_dir))
    tx = transport.SSHTransport(runner=FakeRunner())

    with pytest.raises(engine.RollbackResolutionError, match="no verified recovery point"):
        engine.rollback(repo_root=ROOT, target="conflict", deployment_id="hc-no-recovery", transport=tx)
    assert tx.runner.commands == []


def test_homecontrol_cli_rollback_requires_deployment_id():
    spec = importlib.util.spec_from_file_location("homecontrol_cli_for_rollback_id_gate", ROOT / "homecontrol_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["homecontrol_cli_for_rollback_id_gate"] = module
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc:
        module.main(["rollback", "--target", "jetson", "--yes"])
    assert exc.value.code == 2


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
    joined_commands = [" ".join(cmd) for cmd in tx.runner.commands]
    assert any("api/v1/health" in command for command in joined_commands)
    assert all("docker build" not in command for command in joined_commands)
    assert all("127.0.0.1:8080" not in command for command in joined_commands)


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

    report = engine.deploy(repo_root=ROOT, release="2" * 40, dry_run=False, explicit_all=True, transport=tx, run_tests=False)

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
    assert report["summary"]["status"] == "FAIL"
    assert any(step.get("rollback") for step in report["targets"][0]["steps"])
    rollback_names = [step["name"] for step in report["targets"][0]["steps"] if step.get("rollback")]
    assert "verify_lab_state_safety" in rollback_names
    assert "verify_lab_heartbeat_client" in rollback_names


def test_lab1_backup_creation_failure_does_not_restart_or_restore(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="5" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="lab1_backup="))

    report = engine.deploy(
        repo_root=ROOT,
        release="5" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "FAIL"
    assert not any(step.get("rollback") for step in report["targets"][0]["steps"])
    assert not any("systemctl restart homecontrol-lab.service" in command for command in joined)
    assert not any("lab1_restore=" in command for command in joined)


def test_conflict_backup_failure_before_mutation_does_not_restart_or_restore(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="e" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="heartbeat_backup="))

    report = engine.deploy(
        repo_root=ROOT,
        release="e" * 40,
        target="conflict",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "FAIL"
    assert not any(step.get("rollback") for step in report["targets"][0]["steps"])
    assert not any("systemctl restart hcm-heartbeat.service" in command for command in joined)
    assert not any("heartbeat_restore=" in command for command in joined)


def test_conflict_post_verify_failure_rolls_back_and_does_not_write_new_marker(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="f" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class ConflictVerifyFailureRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.failed = False

        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "heartbeat_status_verify.py" in joined and not self.failed:
                self.failed = True
                return transport.CommandResult(command, 1, "", "missing registered devices")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=ConflictVerifyFailureRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="f" * 40,
        target="conflict",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "ROLLED BACK"
    assert report["summary"]["status"] == "FAIL"
    assert any(step.get("rollback") and step["name"] == "rollback_heartbeat_app" for step in report["targets"][0]["steps"])
    assert not any("tee /var/lib/hcm-heartbeat/homecontrol-release" in command for command in joined)


def test_conflict_failed_rollback_reports_failure_not_success(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="0" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class ConflictRollbackFailureRunner(FakeRunner):
        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "heartbeat_status_verify.py" in joined:
                return transport.CommandResult(command, 1, "", "unexpected active faults")
            if "heartbeat_restore=" in joined:
                return transport.CommandResult(command, 1, "", "restore failed")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=ConflictRollbackFailureRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="0" * 40,
        target="conflict",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["targets"][0]["status"] == "FAIL"
    assert report["summary"]["status"] == "FAIL"
    assert any(step.get("rollback") and step["status"] == "FAIL" for step in report["targets"][0]["steps"])


def test_lab1_post_deploy_state_failure_rolls_back_without_new_marker(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="b" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class PostInstallUnsafeStateRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.installed = False
            self.failed = False

        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "sudo install -m 0755" in joined:
                self.installed = True
            if self.installed and not self.failed and "lab1_state_safety=ok" in joined:
                self.failed = True
                return transport.CommandResult(command, 1, "", "simulation is not true")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=PostInstallUnsafeStateRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="b" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "ROLLED BACK"
    assert not any("tee /opt/homecontrol-lab/state/homecontrol-release" in command for command in joined)


@pytest.mark.parametrize(
    ("name", "needle", "error"),
    [
        ("incorrect_device_id", "lab1_state_safety=ok", "device_id bad != 2ccf675d3414"),
        ("incorrect_hostname", "lab1_state_safety=ok", "hostname wrong != lab1"),
        ("simulation_false", "lab1_state_safety=ok", "simulation is not true"),
        ("physical_outputs_enabled_true", "lab1_state_safety=ok", "physical_outputs_enabled is not false"),
        ("missing_or_malformed_state_json", "lab1_state_safety=ok", "module_state_invalid"),
        ("inactive_lab_service", "homecontrol-lab.service','hcm-heartbeat.service", "homecontrol-lab.service is inactive"),
        ("inactive_heartbeat_service", "homecontrol-lab.service','hcm-heartbeat.service", "hcm-heartbeat.service is inactive"),
        ("heartbeat_status_failure", "heartbeat_client_status_failed", "heartbeat peer offline"),
    ],
)
def test_lab1_post_install_verification_failures_are_failed_rollouts(name, needle, error, tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="c" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class OnePostInstallFailureRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.installed = False
            self.failed = False

        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "sudo install -m 0755" in joined:
                self.installed = True
            if self.installed and not self.failed and needle in joined:
                self.failed = True
                return transport.CommandResult(command, 1, "", error)
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=OnePostInstallFailureRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="c" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert name
    assert report["targets"][0]["status"] == "ROLLED BACK"
    assert report["summary"]["status"] == "FAIL"
    assert any(step["status"] == "FAIL" and error in step["detail"] for step in report["targets"][0]["steps"])


def test_rollback_failure_reports_fail_not_success(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="4" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    class FailingDeployAndRollbackRunner(FakeRunner):
        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "tee /opt/homecontrol-lab/state/homecontrol-release" in joined or "lab1_restore=" in joined:
                return transport.CommandResult(command, 1, "", "forced failure")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=FailingDeployAndRollbackRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="4" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["targets"][0]["status"] == "FAIL"
    assert report["summary"]["status"] == "FAIL"
    assert any(step.get("rollback") and step["status"] == "FAIL" for step in report["targets"][0]["steps"])


def test_lab1_rollback_with_unsafe_state_reports_failure(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="d" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class UnsafeRollbackStateRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.rollback_started = False

        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "tee /opt/homecontrol-lab/state/homecontrol-release" in joined:
                return transport.CommandResult(command, 1, "", "marker failure")
            if "lab1_restore=" in joined:
                self.rollback_started = True
            if self.rollback_started and "lab1_state_safety=ok" in joined:
                return transport.CommandResult(command, 1, "", "physical_outputs_enabled is not false")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=UnsafeRollbackStateRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="d" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["targets"][0]["status"] == "FAIL"
    assert report["summary"]["status"] == "FAIL"
    assert any(
        step.get("rollback") and step["name"] == "verify_lab_state_safety" and step["status"] == "FAIL"
        for step in report["targets"][0]["steps"]
    )


def test_preflight_reports_facts_and_blockers():
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="module.json"))

    report = engine.preflight(repo_root=ROOT, target="lab1", transport=tx)

    assert report["summary"]["status"] == "FAIL"
    assert report["targets"][0]["blockers"]
    assert report["targets"][0]["assumptions"]


def test_hcm_docker_clone_preserves_mounts_networks_environment_and_command(monkeypatch):
    module = load_script_module("hcm_docker_deploy_test", "11_scripts/hcm_docker_deploy.py")
    calls = []

    def fake_docker(method, path, body=None, ok=(200, 201, 204, 304)):
        calls.append((method, path, body))
        return {}

    monkeypatch.setattr(module, "docker", fake_docker)
    source = {
        "Config": {
            "Hostname": "abc",
            "Image": "homecontrol-hcm:old",
            "Env": ["HCM_DATABASE_URL=postgres://redacted"],
            "Cmd": ["python", "-m", "uvicorn", "01_HCM.main:app"],
            "Entrypoint": None,
            "Labels": {"homecontrol": "hcm"},
            "ExposedPorts": {"8080/tcp": {}, "6501/tcp": {}},
            "WorkingDir": "/opt/HomeControl",
            "Tty": False,
            "OpenStdin": False,
        },
        "HostConfig": {
            "Binds": ["/etc/hcm/postgres-password:/run/secrets/postgres_password:ro"],
            "PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]},
            "RestartPolicy": {"Name": "no"},
            "CapAdd": ["NET_ADMIN"],
        },
        "NetworkSettings": {
            "Networks": {
                "hcm-control": {"Aliases": ["hcm-test"], "MacAddress": "02:42:ac:13:00:02", "IPAddress": "172.19.0.2"},
                "hcm-internal": {"Aliases": ["hcm-test"], "IPAMConfig": {"IPv4Address": "172.18.0.9"}},
            }
        },
    }

    module.create_clone(source, image="homecontrol-hcm:new", name="hcm-test")

    create = next(call for call in calls if call[1].startswith("/containers/create"))
    connect = next(call for call in calls if call[1] == "/networks/hcm-internal/connect")
    body = create[2]
    assert body["Image"] == "homecontrol-hcm:new"
    assert body["Env"] == ["HCM_DATABASE_URL=postgres://redacted"]
    assert body["Cmd"] == ["python", "-m", "uvicorn", "01_HCM.main:app"]
    assert body["HostConfig"]["Binds"] == [
        "/etc/hcm/postgres-password:/run/secrets/postgres_password:ro",
        "/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw",
    ]
    assert body["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] == "192.168.20.27"
    assert set(body["NetworkingConfig"]["EndpointsConfig"]) == {"hcm-control"}
    assert body["NetworkingConfig"]["EndpointsConfig"]["hcm-control"]["Aliases"] == ["hcm-test"]
    assert "IPAddress" not in body["NetworkingConfig"]["EndpointsConfig"]["hcm-control"]
    assert connect[2]["Container"] == "hcm-test"
    assert connect[2]["EndpointConfig"]["Aliases"] == ["hcm-test"]
    assert connect[2]["EndpointConfig"]["IPAMConfig"] == {"IPv4Address": "172.18.0.9"}


def test_hcm_docker_clone_preserves_existing_homecontrol_storage_mount(monkeypatch):
    module = load_script_module("hcm_docker_deploy_mount_test", "11_scripts/hcm_docker_deploy.py")
    calls = []

    def fake_docker(method, path, body=None, ok=(200, 201, 204, 304)):
        calls.append((method, path, body))
        return {}

    monkeypatch.setattr(module, "docker", fake_docker)
    source = {
        "Config": {"Image": "old", "Cmd": ["python"], "ExposedPorts": {"8080/tcp": {}}},
        "HostConfig": {
            "Binds": ["/custom/homecontrol:/var/lib/homecontrol:rw"],
            "PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]},
        },
        "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        "Mounts": [{"Destination": "/var/lib/homecontrol"}],
    }

    module.create_clone(source, image="new", name="hcm-test")

    create = next(call for call in calls if call[1].startswith("/containers/create"))
    assert create[2]["HostConfig"]["Binds"].count("/custom/homecontrol:/var/lib/homecontrol:rw") == 1
    assert "/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw" not in create[2]["HostConfig"]["Binds"]


def test_hcm_docker_clone_reports_additional_network_connect_failure(monkeypatch):
    module = load_script_module("hcm_docker_deploy_connect_fail_test", "11_scripts/hcm_docker_deploy.py")
    calls = []

    def fake_docker(method, path, body=None, ok=(200, 201, 204, 304)):
        calls.append((method, path, body))
        if path == "/networks/hcm-internal/connect":
            raise module.DockerDeployError("HTTP 400: connect failed")
        return {}

    monkeypatch.setattr(module, "docker", fake_docker)
    source = {
        "Config": {"Image": "homecontrol-hcm:old", "Cmd": ["run"]},
        "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
        "Mounts": [],
        "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
    }

    with pytest.raises(module.DockerDeployError, match="failure connecting replacement container hcm-test to network hcm-internal"):
        module.create_clone(source, image="homecontrol-hcm:new", name="hcm-test")

    assert any(path.startswith("/containers/create") for _, path, _ in calls)
    assert any(path == "/networks/hcm-internal/connect" for _, path, _ in calls)


def test_hcm_docker_clone_rejects_postgres_data_mount_and_missing_networks():
    module = load_script_module("hcm_docker_deploy_safety_test", "11_scripts/hcm_docker_deploy.py")
    base = {
        "Config": {"Image": "homecontrol-hcm:old"},
        "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
        "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        "Mounts": [],
    }

    module.validate_clone_source(base)
    with pytest.raises(module.DockerDeployError, match="PostgreSQL data mount"):
        bad = dict(base)
        bad["Mounts"] = [{"Destination": "/var/lib/postgresql/data"}]
        module.validate_clone_source(bad)
    with pytest.raises(module.DockerDeployError, match="required HCM Docker networks"):
        bad = dict(base)
        bad["NetworkSettings"] = {"Networks": {"hcm-control": {}}}
        module.validate_clone_source(bad)


def test_hcm_docker_deploy_discovers_health_url_from_port_binding(monkeypatch):
    module = load_script_module("hcm_docker_deploy_health_test", "11_scripts/hcm_docker_deploy.py")

    def fake_inspect(name):
        return {
            "HostConfig": {
                "PortBindings": {
                    "8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}],
                    "6501/tcp": [{"HostIp": "192.168.20.27", "HostPort": "6501"}],
                }
            }
        }

    monkeypatch.setattr(module, "inspect_container", fake_inspect)

    assert module.published_health_url("hcm-test") == "http://192.168.20.27:8080/api/v1/health"


def test_hcm_docker_deploy_rejects_ambiguous_loopback_fallback(monkeypatch):
    module = load_script_module("hcm_docker_deploy_ambiguous_test", "11_scripts/hcm_docker_deploy.py")

    def fake_inspect(name):
        return {"HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}}}

    monkeypatch.setattr(module, "inspect_container", fake_inspect)

    with pytest.raises(module.DockerDeployError, match="expected one concrete"):
        module.published_health_url("hcm-test")


def test_hcm_docker_deploy_refuses_existing_rollback_container(monkeypatch):
    module = load_script_module("hcm_docker_deploy_existing_rollback_test", "11_scripts/hcm_docker_deploy.py")
    removed = []

    def fake_inspect(name):
        if name in {"hcm-test", "hcm-rollback-hc-old"}:
            return {
                "Id": name,
                "Config": {"Image": "old"},
                "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
                "Mounts": [],
                "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
            }
        raise module.DockerDeployError("missing {}".format(name))

    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "remove_container", lambda name: removed.append(name))

    with pytest.raises(module.DockerDeployError, match="already exists"):
        module.deploy("new-image", expected_sha="a" * 40, name="hcm-test", rollback_name="hcm-rollback-hc-old", health_url=None, timeout=1, deployment_id="hc-new")

    assert removed == []


def test_jetson_adapter_uses_deployment_specific_rollback_name():
    fake_artifact = artifact.ReleaseArtifact(
        release="a" * 40,
        path=Path("/tmp/homecontrol.tar.gz"),
        sha256="abc123",
        metadata_path=Path("/tmp/homecontrol.json"),
    )
    adapter = adapters.adapter_for(inventory.inventory()["jetson"])
    steps = adapter.steps(fake_artifact, deployment_id="hc-20261012T000000Z-abcd1234")
    replace = next(step.command for step in steps if step.name == "replace_hcm_container")

    assert "--rollback-name hcm-rollback-hc-20261012T000000Z-abcd1234" in replace
    assert "--deployment-id hc-20261012T000000Z-abcd1234" in replace
    assert "hcm-rollback-before-deploy" not in replace


def test_safety_gate_checks_adapter_read_only_steps(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="b" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)
    tx = transport.SSHTransport(runner=FakeRunner(fail_contains="test -e /opt/homecontrol-lab/backups"))

    report = engine.deploy(
        repo_root=ROOT,
        release="b" * 40,
        target="lab1",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    assert report["summary"]["status"] == "FAIL"
    assert report["targets"][0]["steps"][0]["name"] == "predeployment_safety_gate"
    joined = [" ".join(command) for command in tx.runner.commands]
    assert not any("scp" == command[0] for command in tx.runner.commands)
    assert not any("systemctl restart homecontrol-lab.service" in command for command in joined)


def test_jetson_replace_failure_with_internal_recovery_does_not_attempt_duplicate_framework_rollback(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="6" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class JetsonReplaceRecoveredRunner(FakeRunner):
        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "hcm_docker_deploy.py deploy" in joined:
                return transport.CommandResult(
                    command,
                    1,
                    "",
                    "failure creating replacement container hcm-test image homecontrol-hcm:roles: HTTP 400: Container cannot be connected to network endpoints: hcm-control, hcm-internal; recovery=original_container_restored_from_hcm-rollback-hc-20261012T031811Z-2ce2d59a_id_abc123_health=ok",
                )
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=JetsonReplaceRecoveredRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="6" * 40,
        target="jetson",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "FAIL"
    assert report["summary"]["status"] == "FAIL"
    assert not any(step.get("rollback") for step in report["targets"][0]["steps"])
    assert sum("hcm_docker_deploy.py rollback" in command for command in joined) == 0
    assert any("hcm-postgres" in command for command in joined)
    assert not any("rm hcm-postgres" in command or "stop hcm-postgres" in command for command in joined)


def test_jetson_post_replace_verification_failure_uses_deployment_specific_framework_rollback(tmp_path, monkeypatch):
    fake_artifact = artifact.ReleaseArtifact(
        release="7" * 40,
        path=tmp_path / "homecontrol.tar.gz",
        sha256="abc123",
        metadata_path=tmp_path / "homecontrol.json",
    )
    fake_artifact.path.write_text("artifact")
    fake_artifact.metadata_path.write_text("{}")
    monkeypatch.setattr(engine.artifact_mod, "create_release_artifact", lambda repo_root, release, output_dir: fake_artifact)

    class JetsonVerifyFailureRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.replaced = False
            self.failed = False

        def __call__(self, command, *, input=None, timeout=None):
            self.commands.append(command)
            joined = " ".join(command)
            if "hcm_docker_deploy.py deploy" in joined:
                self.replaced = True
            if self.replaced and not self.failed and "api/v1/health" in joined:
                self.failed = True
                return transport.CommandResult(command, 1, "", "health failed after replacement")
            return transport.CommandResult(command, 0, "ok\n", "")

    tx = transport.SSHTransport(runner=JetsonVerifyFailureRunner())

    report = engine.deploy(
        repo_root=ROOT,
        release="7" * 40,
        target="jetson",
        dry_run=False,
        transport=tx,
        run_tests=False,
    )

    joined = [" ".join(command) for command in tx.runner.commands]
    assert report["targets"][0]["status"] == "ROLLED BACK"
    assert report["summary"]["status"] == "FAIL"
    rollback_commands = [command for command in joined if "hcm_docker_deploy.py rollback" in command]
    assert len(rollback_commands) == 1
    assert "--rollback-name hcm-rollback-hc-" in rollback_commands[0]
    assert "hcm-rollback-" + "7" * 40 not in rollback_commands[0]


@pytest.mark.parametrize("failure", ["health", "runtime_identity"])
def test_hcm_docker_deploy_rolls_back_when_health_check_fails(monkeypatch, failure):
    module = load_script_module("hcm_docker_deploy_rollback_test", "11_scripts/hcm_docker_deploy.py")
    calls = []
    containers = {"hcm-test": "old-container-id"}

    def fake_inspect(name):
        if name not in containers:
            raise module.DockerDeployError("missing {}".format(name))
        return {
            "Id": containers[name],
            "Config": {"Image": "old"},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
            "Mounts": [],
            "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        }

    def fake_create_clone(source, image, name):
        calls.append(("create", name, image))
        containers[name] = "new-container-id"

    def fake_stop(name):
        calls.append(("stop", name))

    def fake_start(name):
        calls.append(("start", name))

    def fake_rename(old, new):
        calls.append(("rename", old, new))
        containers[new] = containers.pop(old)

    def fake_remove(name):
        calls.append(("remove", name))
        containers.pop(name, None)

    def fake_healthcheck(name, url, timeout):
        calls.append(("health", name))
        if failure == "health":
            raise module.DockerDeployError("health failed")

    def fail_verification(*args):
        raise RuntimeError("runtime SHA mismatch")
    monkeypatch.setitem(sys.modules, "hcm_verify", SimpleNamespace(verify_runtime=fail_verification))
    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "create_clone", fake_create_clone)
    monkeypatch.setattr(module, "stop_container", fake_stop)
    monkeypatch.setattr(module, "start_container", fake_start)
    monkeypatch.setattr(module, "rename_container", fake_rename)
    monkeypatch.setattr(module, "remove_container", fake_remove)
    monkeypatch.setattr(module, "healthcheck", fake_healthcheck)

    with pytest.raises(module.DockerDeployError, match="health failed" if failure == "health" else "runtime SHA mismatch"):
        module.deploy("new-image", expected_sha="a" * 40, name="hcm-test", rollback_name="hcm-rollback-before-deploy", health_url=None, timeout=1)

    assert ("rename", "hcm-test", "hcm-rollback-before-deploy") in calls
    assert ("remove", "hcm-test") in calls
    assert ("rename", "hcm-rollback-before-deploy", "hcm-test") in calls
    assert ("start", "hcm-test") in calls


def test_hcm_docker_deploy_restores_previous_when_create_fails(monkeypatch):
    module = load_script_module("hcm_docker_deploy_create_fail_test", "11_scripts/hcm_docker_deploy.py")
    calls = []
    containers = {"hcm-test"}

    def fake_inspect(name):
        if name not in containers:
            raise module.DockerDeployError("missing {}".format(name))
        return {
            "Id": "old-container-id",
            "Config": {"Image": "old"},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
            "Mounts": [],
            "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        }

    def fake_rename(old, new):
        calls.append(("rename", old, new))
        containers.remove(old)
        containers.add(new)

    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "stop_container", lambda name: calls.append(("stop", name)))
    monkeypatch.setattr(module, "start_container", lambda name: calls.append(("start", name)))
    monkeypatch.setattr(module, "rename_container", fake_rename)
    monkeypatch.setattr(module, "remove_container", lambda name: (calls.append(("remove", name)), containers.discard(name)))
    monkeypatch.setattr(module, "create_clone", lambda source, image, name: (_ for _ in ()).throw(module.DockerDeployError("create failed")))
    monkeypatch.setattr(module, "healthcheck", lambda name, url, timeout: calls.append(("health", name)))

    with pytest.raises(module.DockerDeployError, match="create failed"):
        module.deploy("new-image", expected_sha="a" * 40, name="hcm-test", rollback_name="hcm-rollback-hc-new", health_url=None, timeout=1, deployment_id="hc-new")

    assert ("rename", "hcm-test", "hcm-rollback-hc-new") in calls
    assert ("rename", "hcm-rollback-hc-new", "hcm-test") in calls
    assert ("start", "hcm-test") in calls


@pytest.mark.parametrize(
    ("stage", "message"),
    [
        ("stop", "failure stopping original container"),
        ("rename", "failure renaming original container"),
        ("start", "failure starting replacement container"),
    ],
)
def test_hcm_docker_deploy_reports_stage_failures_and_attempts_safe_recovery(stage, message, monkeypatch):
    module = load_script_module("hcm_docker_deploy_stage_failure_test_" + stage, "11_scripts/hcm_docker_deploy.py")
    calls = []
    containers = {"hcm-test": "old-container-id"}

    def fake_inspect(name):
        if name not in containers:
            raise module.DockerDeployError("missing {}".format(name))
        return {
            "Id": containers[name],
            "Config": {"Image": "old"},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
            "Mounts": [],
            "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        }

    def fake_stop(name):
        calls.append(("stop", name))
        if stage == "stop" and name == "hcm-test" and "hcm-rollback-hc-new" not in containers:
            raise module.DockerDeployError("stop failed")

    def fake_rename(old, new):
        calls.append(("rename", old, new))
        if stage == "rename":
            raise module.DockerDeployError("rename failed")
        containers[new] = containers.pop(old)

    def fake_create(source, image, name):
        calls.append(("create", name))
        containers[name] = "new-container-id"

    def fake_start(name):
        calls.append(("start", name))
        if stage == "start" and containers.get(name) == "new-container-id":
            raise module.DockerDeployError("start failed")

    def fake_remove(name):
        calls.append(("remove", name))
        containers.pop(name, None)

    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "stop_container", fake_stop)
    monkeypatch.setattr(module, "rename_container", fake_rename)
    monkeypatch.setattr(module, "create_clone", fake_create)
    monkeypatch.setattr(module, "start_container", fake_start)
    monkeypatch.setattr(module, "remove_container", fake_remove)
    monkeypatch.setattr(module, "healthcheck", lambda name, url, timeout: calls.append(("health", name)))

    with pytest.raises(module.DockerDeployError, match=message):
        module.deploy("new-image", expected_sha="a" * 40, name="hcm-test", rollback_name="hcm-rollback-hc-new", health_url=None, timeout=1)

    assert containers.get("hcm-test") == "old-container-id"
    assert "hcm-rollback-hc-new" not in containers


def test_hcm_docker_deploy_identity_mismatch_requires_manual_intervention(monkeypatch):
    module = load_script_module("hcm_docker_deploy_identity_mismatch_test", "11_scripts/hcm_docker_deploy.py")
    containers = {"hcm-test": "old-container-id"}

    def fake_inspect(name):
        if name not in containers:
            raise module.DockerDeployError("missing {}".format(name))
        return {
            "Id": containers[name],
            "Config": {"Image": "old"},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "192.168.20.27", "HostPort": "8080"}]}},
            "Mounts": [],
            "NetworkSettings": {"Networks": {"hcm-control": {}, "hcm-internal": {}}},
        }

    def fake_rename(old, new):
        containers.pop(old)
        containers[new] = "unexpected-container-id"

    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "stop_container", lambda name: None)
    monkeypatch.setattr(module, "rename_container", fake_rename)

    with pytest.raises(module.DockerDeployError, match="manual intervention required"):
        module.deploy("new-image", expected_sha="a" * 40, name="hcm-test", rollback_name="hcm-rollback-hc-new", health_url=None, timeout=1)

    assert containers == {"hcm-rollback-hc-new": "unexpected-container-id"}


def test_hcm_docker_deploy_never_removes_ambiguous_active_container(monkeypatch):
    module = load_script_module("hcm_docker_deploy_ambiguous_recovery_test", "11_scripts/hcm_docker_deploy.py")
    removed = []
    containers = {
        "hcm-test": "unexpected-active-id",
        "hcm-rollback-hc-new": "unexpected-rollback-id",
    }

    def fake_inspect(name):
        if name not in containers:
            raise module.DockerDeployError("missing {}".format(name))
        return {"Id": containers[name]}

    monkeypatch.setattr(module, "inspect_container", fake_inspect)
    monkeypatch.setattr(module, "remove_container", lambda name: removed.append(name))

    with pytest.raises(module.DockerDeployError, match="manual intervention required"):
        module.recover_original_container("hcm-test", "hcm-rollback-hc-new", "old-container-id", None, 1)

    assert removed == []


def test_hcm_docker_deploy_python36_parse_compatible():
    import ast

    source = (ROOT / "11_scripts" / "hcm_docker_deploy.py").read_text()
    ast.parse(source, filename="hcm_docker_deploy.py", feature_version=(3, 6))


def test_cli_exit_code_helper_flags_failed_reports():
    spec = importlib.util.spec_from_file_location("homecontrol_cli_for_exit_test", ROOT / "homecontrol_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["homecontrol_cli_for_exit_test"] = module
    spec.loader.exec_module(module)

    assert module._exit_for_report({"summary": {"status": "FAIL"}}) == 1
    assert module._exit_for_report({"summary": {"status": "ROLLED BACK"}}) == 1
    assert module._exit_for_report({"summary": {"status": "PASS"}}) == 0
    assert module._exit_for_report({"summary": {"status": "NO CHANGE"}}) == 0


def test_jetson_schema_gate_precedes_container_replacement():
    adapter = adapters.adapter_for(inventory.inventory()['jetson'])
    release = artifact.ReleaseArtifact('a' * 40, Path('/tmp/release.tar.gz'), 'digest', Path('/tmp/meta.json'))
    steps = adapter.steps(release, deployment_id='schema-test')
    names = [step.name for step in steps]
    assert names.index('verify_hcm_schema') < names.index('replace_hcm_container')
    gate = next(step for step in steps if step.name == 'verify_hcm_schema')
    assert 'transaction(readonly=True)' in gate.command
    assert not adapter.framework_rollback_needed(gate, RuntimeError('missing schema'))
    assert 'migrate' not in gate.command


def test_release_marker_writes_real_newline():
    adapter = adapters.adapter_for(inventory.inventory()['jetson'])
    release = artifact.ReleaseArtifact('a' * 40, Path('/tmp/release.tar.gz'), 'digest', Path('/tmp/meta.json'))
    command = next(s.command for s in adapter.steps(release) if s.name == 'record_release')
    # Execute only printf locally; no sudo or writes.
    output = subprocess.check_output(['sh', '-c', command.split('|')[0]])
    assert output == ('a' * 40 + '\n').encode()


def test_jetson_gpio_mapping_is_minimal_and_persistent(tmp_path, monkeypatch):
    import types
    module = load_script_module('hcm_gpio_clone_test', '11_scripts/hcm_docker_deploy.py')
    wiring = tmp_path / 'safety-inputs.json'
    wiring.write_text(json.dumps({'gpio_abi': 'v1', 'connected_inputs': []}))
    monkeypatch.setitem(sys.modules, 'hcm_gpio_access', types.SimpleNamespace(verify_chip=lambda: None))
    monkeypatch.setattr(module.grp, 'getgrnam', lambda name: types.SimpleNamespace(gr_gid=995))
    host = {'Privileged': False, 'Binds': ['/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw'], 'GroupAdd': ['994']}
    module.configure_safety_gpio(host, str(wiring))
    module.configure_safety_gpio(host, str(wiring))
    assert host['Devices'] == [{'PathOnHost': '/dev/gpiochip0', 'PathInContainer': '/dev/gpiochip0', 'CgroupPermissions': 'r'}]
    assert host['GroupAdd'] == ['994', '995']
    assert host['Binds'] == ['/srv/hcm-data/homecontrol:/var/lib/homecontrol:rw', str(wiring)+':/etc/hcm/safety-inputs.json:ro']
    host['Privileged'] = True
    with pytest.raises(module.DockerDeployError, match='privileged'):
        module.configure_safety_gpio(host, str(wiring))
