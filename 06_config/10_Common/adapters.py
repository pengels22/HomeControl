from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .artifact import ReleaseArtifact
    from .inventory import DeviceInventoryEntry
    from .transport import SSHTransport
except ImportError:
    from artifact import ReleaseArtifact  # type: ignore
    from inventory import DeviceInventoryEntry  # type: ignore
    from transport import SSHTransport  # type: ignore


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterStep:
    name: str
    command: str
    changes_system: bool = False
    timeout: int = 60


@dataclass(frozen=True)
class AdapterResult:
    target: str
    status: str
    steps: list[dict[str, Any]]


class BaseAdapter:
    adapter_name = "base"

    def __init__(self, entry: DeviceInventoryEntry):
        self.entry = entry

    def steps(self, artifact: ReleaseArtifact) -> list[AdapterStep]:
        remote_archive = self.remote_archive_path(artifact)
        release_dir = self.release_dir(artifact)
        return [
            AdapterStep("check_installed_release", f"test -f {self.release_marker()} && cat {self.release_marker()} || true"),
            AdapterStep("remote_identity", "hostname && uname -a", timeout=20),
            AdapterStep("stage_directory", f"mkdir -p {release_dir}"),
            AdapterStep("transfer_artifact", f"scp:{remote_archive}"),
            AdapterStep("extract_release", f"tar -xzf {remote_archive} -C {release_dir} --strip-components=0"),
            AdapterStep("verify_release", f"test -f {release_dir}/06_config/{self.entry.package}/manifest.yaml"),
        ]

    def remote_archive_path(self, artifact: ReleaseArtifact) -> str:
        return f"/tmp/{artifact.path.name}"

    def release_dir(self, artifact: ReleaseArtifact) -> str:
        return f"/tmp/homecontrol-release-{artifact.release}"

    def release_marker(self) -> str:
        return "/var/lib/homecontrol-deploy/current-release"

    def dry_run(self, artifact: ReleaseArtifact) -> AdapterResult:
        return AdapterResult(
            target=self.entry.name,
            status="PLANNED",
            steps=[
                {"name": step.name, "status": "PLANNED", "detail": step.command, "changes_system": step.changes_system}
                for step in self.steps(artifact)
            ],
        )

    def preflight_steps(self) -> list[AdapterStep]:
        return [
            AdapterStep("remote_identity", "hostname && uname -a", timeout=20),
            AdapterStep("read_release_marker", f"test -f {self.release_marker()} && cat {self.release_marker()} || true"),
        ]

    def preflight(self, transport: SSHTransport) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        status = "PASS"
        for step in self.preflight_steps():
            try:
                result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout)
            except Exception as exc:
                status = "FAIL"
                executed.append({"name": step.name, "status": "FAIL", "detail": str(exc), "fact": False})
            else:
                executed.append({"name": step.name, "status": "PASS", "detail": result.stdout.strip(), "fact": True})
        return AdapterResult(target=self.entry.name, status=status, steps=executed)

    def apply(self, transport: SSHTransport, artifact: ReleaseArtifact) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        changed = False
        for step in self.steps(artifact):
            try:
                if step.name == "check_installed_release":
                    result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout)
                    installed = result.stdout.strip()
                    executed.append(
                        {"name": step.name, "status": "PASS", "detail": installed or "not installed", "changes_system": False}
                    )
                    if installed == artifact.release:
                        executed.append(
                            {"name": "no_op", "status": "NO CHANGE", "detail": "target already reports selected release", "changes_system": False}
                        )
                        return AdapterResult(target=self.entry.name, status="NO CHANGE", steps=executed)
                    continue
                if step.name == "transfer_artifact":
                    transport.transfer_file(self.entry.ssh_alias, artifact.path, self.remote_archive_path(artifact), timeout=step.timeout)
                else:
                    transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout)
            except Exception as exc:
                executed.append(
                    {"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": step.changes_system}
                )
                if changed or step.changes_system:
                    rollback = self.rollback_after_failure(transport, artifact)
                    executed.extend({"rollback": True, **item} for item in rollback.steps)
                    if rollback.status == "PASS":
                        return AdapterResult(target=self.entry.name, status="ROLLED BACK", steps=executed)
                return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
            if step.changes_system:
                changed = True
            executed.append(
                {"name": step.name, "status": "PASS", "detail": step.command, "changes_system": step.changes_system}
            )
        return AdapterResult(target=self.entry.name, status="PASS", steps=executed)

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        return [AdapterStep("rollback_not_implemented", "false")]

    def rollback(self, transport: SSHTransport) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps())

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps(artifact))

    def _run_rollback_steps(self, transport: SSHTransport, steps: list[AdapterStep]) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        for step in steps:
            try:
                transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout)
            except Exception as exc:
                executed.append({"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": step.changes_system})
                return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
            executed.append({"name": step.name, "status": "PASS", "detail": step.command, "changes_system": step.changes_system})
        return AdapterResult(target=self.entry.name, status="PASS", steps=executed)


class ConflictAdapter(BaseAdapter):
    adapter_name = "conflict_heartbeat"

    def steps(self, artifact: ReleaseArtifact) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        return super().steps(artifact) + [
            AdapterStep("preflight_auth", "test -f /etc/hcm-heartbeat/config.json && python3 -m json.tool /etc/hcm-heartbeat/config.json >/dev/null"),
            AdapterStep("online_sqlite_backup", f"sudo {release_dir}/10_scripts/heartbeat_backup.sh conflict", changes_system=True, timeout=120),
            AdapterStep("install_heartbeat_skip_start", f"cd {release_dir}/00_Heartbeat && sudo HC_SKIP_START=1 ./install.sh conflict", changes_system=True, timeout=120),
            AdapterStep("restart_heartbeat", "sudo systemctl restart hcm-heartbeat.service", changes_system=True, timeout=60),
            AdapterStep("verify_heartbeat", f"HC_HEARTBEAT_DB=/var/lib/hcm-heartbeat/registry.sqlite3 {release_dir}/10_scripts/heartbeat_verify_readonly.sh http://127.0.0.1:6004 && curl -fsS http://127.0.0.1:6004/status | python3 - <<'PY'\nimport json,sys\ns=json.load(sys.stdin).get('status',{{}}).get('registry',{{}})\nmissing=[d for d in ('48b02d87db16','2ccf675d3414') if d not in s]\nassert not missing, missing\nPY", timeout=60),
            AdapterStep("record_release", f"sudo install -d -m 0755 /var/lib/hcm-heartbeat && printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def release_marker(self) -> str:
        return "/var/lib/hcm-heartbeat/homecontrol-release"

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("heartbeat_paths", "test -f /etc/hcm-heartbeat/config.json && test -f /var/lib/hcm-heartbeat/registry.sqlite3 && test -x /usr/local/bin/hcm-heartbeat"),
            AdapterStep("heartbeat_auth_config", "python3 - <<'PY'\nimport json,os,stat\nc=json.load(open('/etc/hcm-heartbeat/config.json'))\nassert c.get('heartbeat_auth_mode') == 'hmac-sha256'\np=c.get('heartbeat_auth_secret_file')\nassert p and os.path.exists(p)\nassert os.stat(p).st_mode & 0o077 == 0\nPY"),
            AdapterStep("heartbeat_registry", "python3 - <<'PY'\nimport sqlite3\nconn=sqlite3.connect('/var/lib/hcm-heartbeat/registry.sqlite3')\ntry:\n print(conn.execute('PRAGMA integrity_check').fetchone()[0])\n for t in ('authorized_devices','devices','heartbeat_events'):\n  conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()\nfinally:\n conn.close()\nPY"),
        ]

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        return [
            AdapterStep("manual_backup_required", "test -n \"${HC_CONFLICT_ROLLBACK_BACKUP:-}\""),
            AdapterStep("rollback_heartbeat", "sudo 10_scripts/heartbeat_rollback.sh \"$HC_CONFLICT_ROLLBACK_BACKUP\"", changes_system=True, timeout=120),
        ]


class JetsonDockerAdapter(BaseAdapter):
    adapter_name = "hcm_docker"

    def steps(self, artifact: ReleaseArtifact) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        image = f"homecontrol-hcm:{artifact.release}"
        return super().steps(artifact) + [
            AdapterStep("preflight_docker_layout", self._docker_preflight_command()),
            AdapterStep("build_hcm_image", f"sudo docker build -t {image} -f {release_dir}/06_config/01_HCM/Dockerfile.live {release_dir}", changes_system=True, timeout=600),
            AdapterStep("replace_hcm_container", f"sudo python3 {release_dir}/10_scripts/hcm_docker_deploy.py deploy --image {image}", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", "curl -fsS http://127.0.0.1:8080/api/v1/health >/dev/null && systemctl is-active --quiet hcm-watchdog.timer && systemctl is-active --quiet hcm-heartbeat.service", timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def _docker_preflight_command(self) -> str:
        return (
            "test -f /etc/hcm/hcm.env && "
            "systemctl cat hcm.service >/dev/null && "
            "sudo docker inspect hcm-test hcm-postgres >/dev/null && "
            "sudo docker network inspect hcm-control >/dev/null && "
            "sudo docker network inspect hcm-internal >/dev/null && "
            "sudo docker inspect hcm-test | python3 - <<'PY'\n"
            "import json,sys\n"
            "c=json.load(sys.stdin)[0]\n"
            "nets=set(c['NetworkSettings']['Networks'])\n"
            "assert {'hcm-control','hcm-internal'} <= nets, nets\n"
            "ports=c['HostConfig'].get('PortBindings') or {}\n"
            "assert '8080/tcp' in ports, ports\n"
            "assert c['Config'].get('Cmd'), 'missing startup command'\n"
            "PY"
        )

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("hcm_systemd_unit", "systemctl cat hcm.service && systemctl is-enabled hcm.service || true"),
            AdapterStep("hcm_docker_layout", self._docker_preflight_command()),
            AdapterStep("hcm_no_db_migration", "test -d /srv/hcm-data/postgres && sudo docker inspect hcm-postgres >/dev/null"),
        ]

    def release_marker(self) -> str:
        return "/etc/hcm/homecontrol-release"

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        if artifact:
            helper = f"{self.release_dir(artifact)}/10_scripts/hcm_docker_deploy.py"
        else:
            helper = "/tmp/homecontrol-current/10_scripts/hcm_docker_deploy.py"
        return [
            AdapterStep("restore_previous_container", f"sudo python3 {helper} rollback", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", "curl -fsS http://127.0.0.1:8080/api/v1/health >/dev/null", timeout=60),
        ]


class Lab1Adapter(BaseAdapter):
    adapter_name = "lab1_simulation"

    def steps(self, artifact: ReleaseArtifact) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        safety_check = (
            "test \"$(hostname)\" = lab1 && "
            "test -f /opt/homecontrol-lab/state/module.json && "
            "python3 - <<'PY'\n"
            "import json\n"
            "s=json.load(open('/opt/homecontrol-lab/state/module.json'))\n"
            "assert s.get('device_id') == '2ccf675d3414'\n"
            "assert s.get('physical_outputs_enabled') is False\n"
            "assert s.get('simulation') is True\n"
            "PY"
        )
        return super().steps(artifact) + [
            AdapterStep("preflight_lab1_safety", safety_check),
            AdapterStep("backup_lab_agent_components", "sudo install -d -m 0755 /opt/homecontrol-lab/backups && sudo cp -a /opt/homecontrol-lab/lab1_role_agent.py /opt/homecontrol-lab/backups/lab1_role_agent.py.previous", changes_system=True),
            AdapterStep("install_role_helper", f"sudo install -m 0755 {release_dir}/10_scripts/lab1_role_agent.py /opt/homecontrol-lab/lab1_role_agent.py", changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_services", "systemctl is-active --quiet homecontrol-lab.service && systemctl is-active --quiet hcm-heartbeat.service && test -S /run/hcm-heartbeat/control.sock", timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def release_marker(self) -> str:
        return "/opt/homecontrol-lab/state/homecontrol-release"

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("lab1_agent_layout", "test \"$(hostname)\" = lab1 && test -f /opt/homecontrol-lab/lab_agent.py && test -f /opt/homecontrol-lab/lab1_role_agent.py && test -f /opt/homecontrol-lab/state/module.json"),
            AdapterStep("lab1_state_safety", "python3 - <<'PY'\nimport json\ns=json.load(open('/opt/homecontrol-lab/state/module.json'))\nassert s.get('device_id') == '2ccf675d3414'\nassert s.get('hostname') == 'lab1'\nassert s.get('simulation') is True\nassert s.get('physical_outputs_enabled') is False\nassert 'role' in s\nPY"),
            AdapterStep("lab1_services", "systemctl is-active --quiet homecontrol-lab.service && systemctl is-active --quiet hcm-heartbeat.service"),
        ]

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        return [
            AdapterStep("restore_role_helper", "sudo install -m 0755 /opt/homecontrol-lab/backups/lab1_role_agent.py.previous /opt/homecontrol-lab/lab1_role_agent.py", changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_services", "systemctl is-active --quiet homecontrol-lab.service && systemctl is-active --quiet hcm-heartbeat.service", timeout=60),
        ]


def adapter_for(entry: DeviceInventoryEntry) -> BaseAdapter:
    if entry.live_adapter == "conflict_heartbeat":
        return ConflictAdapter(entry)
    if entry.live_adapter == "hcm_docker":
        return JetsonDockerAdapter(entry)
    if entry.live_adapter == "lab1_simulation":
        return Lab1Adapter(entry)
    raise AdapterError(f"unsupported live adapter {entry.live_adapter!r}")
