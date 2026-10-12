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

    def steps(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> list[AdapterStep]:
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

    def dry_run(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        return AdapterResult(
            target=self.entry.name,
            status="PLANNED",
            steps=[
                {"name": step.name, "status": "PLANNED", "detail": step.command, "changes_system": step.changes_system}
                for step in self.steps(artifact, deployment_id=deployment_id)
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
                result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name, read_only=True)
            except Exception as exc:
                status = "FAIL"
                executed.append({"name": step.name, "status": "FAIL", "detail": str(exc), "fact": False})
            else:
                executed.append({"name": step.name, "status": "PASS", "detail": result.stdout.strip(), "fact": True})
        return AdapterResult(target=self.entry.name, status=status, steps=executed)

    def apply(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        changed = False
        for step in self.steps(artifact, deployment_id=deployment_id):
            try:
                if step.name == "check_installed_release":
                    result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name, read_only=True)
                    installed = result.stdout.strip()
                    executed.append(
                        {"name": step.name, "status": "PASS", "detail": installed or "not installed", "changes_system": False}
                    )
                    if installed == artifact.release:
                        health = self.verify_no_change(transport)
                        executed.extend(health.steps)
                        if health.status != "PASS":
                            return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
                        executed.append(
                            {"name": "no_op", "status": "NO CHANGE", "detail": "target already reports selected release and health checks passed", "changes_system": False}
                        )
                        return AdapterResult(target=self.entry.name, status="NO CHANGE", steps=executed)
                    continue
                if step.name == "transfer_artifact":
                    transport.transfer_file(self.entry.ssh_alias, artifact.path, self.remote_archive_path(artifact), timeout=step.timeout)
                else:
                    transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name)
            except Exception as exc:
                executed.append(
                    {"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": step.changes_system}
                )
                if changed or step.changes_system:
                    rollback = self.rollback_after_failure(transport, artifact, deployment_id=deployment_id)
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

    def no_change_health_steps(self) -> list[AdapterStep]:
        return self.preflight_steps()

    def verify_no_change(self, transport: SSHTransport) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        for step in self.no_change_health_steps():
            try:
                result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name, read_only=True)
            except Exception as exc:
                executed.append({"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": False})
                return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
            executed.append({"name": step.name, "status": "PASS", "detail": result.stdout.strip() or step.command, "changes_system": False})
        return AdapterResult(target=self.entry.name, status="PASS", steps=executed)

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        return [AdapterStep("rollback_not_implemented", "false")]

    def rollback(self, transport: SSHTransport) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps())

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps(artifact))

    def _run_rollback_steps(self, transport: SSHTransport, steps: list[AdapterStep]) -> AdapterResult:
        executed: list[dict[str, Any]] = []
        for step in steps:
            try:
                transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name)
            except Exception as exc:
                executed.append({"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": step.changes_system})
                return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
            executed.append({"name": step.name, "status": "PASS", "detail": step.command, "changes_system": step.changes_system})
        return AdapterResult(target=self.entry.name, status="PASS", steps=executed)


class ConflictAdapter(BaseAdapter):
    adapter_name = "conflict_heartbeat"

    def steps(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        backup_dir = f"/var/backups/homecontrol-heartbeat/app-rollback-{artifact.release}"
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_auth", "sudo -n python3 - <<'PY'\nimport json,os,stat\ncfg=json.load(open('/etc/hcm-heartbeat/config.json'))\nassert cfg.get('heartbeat_auth_mode') == 'hmac-sha256'\npath=cfg.get('heartbeat_auth_secret_file')\nassert path and os.path.exists(path)\nmode=stat.S_IMODE(os.stat(path).st_mode)\nassert mode == 0o600, oct(mode)\nprint('auth_mode=hmac-sha256 secret_present=true secret_mode=0600')\nPY"),
            AdapterStep("online_sqlite_backup", f"sudo sh -c 'HC_HEARTBEAT_BACKUP_DIR={backup_dir} {release_dir}/10_scripts/heartbeat_backup.sh conflict >/tmp/homecontrol-heartbeat-backup-path && ln -sfn {backup_dir} /var/backups/homecontrol-heartbeat/homecontrol-deploy-rollback'", changes_system=True, timeout=120),
            AdapterStep("install_heartbeat_skip_start", f"cd {release_dir}/00_Heartbeat && sudo HC_SKIP_START=1 ./install.sh conflict", changes_system=True, timeout=120),
            AdapterStep("restart_heartbeat", "sudo systemctl restart hcm-heartbeat.service", changes_system=True, timeout=60),
            AdapterStep("verify_heartbeat", self._heartbeat_verify_command(script=f"{release_dir}/10_scripts/heartbeat_verify_readonly.sh"), timeout=60),
            AdapterStep("record_release", f"sudo install -d -m 0755 /var/lib/hcm-heartbeat && printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def release_marker(self) -> str:
        return "/var/lib/hcm-heartbeat/homecontrol-release"

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("heartbeat_paths", "sudo -n test -f /etc/hcm-heartbeat/config.json && sudo -n test -f /var/lib/hcm-heartbeat/registry.sqlite3 && test -x /usr/local/bin/hcm-heartbeat && test -f /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py"),
            AdapterStep("heartbeat_auth_config", "sudo -n python3 - <<'PY'\nimport json,os,stat\nc=json.load(open('/etc/hcm-heartbeat/config.json'))\nassert c.get('heartbeat_auth_mode') == 'hmac-sha256'\np=c.get('heartbeat_auth_secret_file')\nassert p and os.path.exists(p)\nst=os.stat(p)\nmode=stat.S_IMODE(st.st_mode)\nassert mode == 0o600, oct(mode)\nprint('auth_mode=hmac-sha256 secret_present=true secret_mode=0600 secret_uid={}'.format(st.st_uid))\nPY"),
            AdapterStep("heartbeat_registry", "sudo -n python3 - <<'PY'\nimport sqlite3\nconn=sqlite3.connect('/var/lib/hcm-heartbeat/registry.sqlite3')\ntry:\n print('integrity={}'.format(conn.execute('PRAGMA integrity_check').fetchone()[0]))\n for t in ('authorized_devices','devices','heartbeat_events'):\n  print('{}={}'.format(t, conn.execute('SELECT COUNT(*) FROM {}'.format(t)).fetchone()[0]))\nfinally:\n conn.close()\nPY"),
            AdapterStep("heartbeat_service", self._heartbeat_service_command()),
        ]

    def no_change_health_steps(self) -> list[AdapterStep]:
        return [
            AdapterStep("heartbeat_service", self._heartbeat_service_command()),
            AdapterStep("heartbeat_registry", "sudo -n python3 - <<'PY'\nimport sqlite3\nconn=sqlite3.connect('/var/lib/hcm-heartbeat/registry.sqlite3')\ntry:\n assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'\nfinally:\n conn.close()\nPY"),
        ]

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        backup_dir = f"/var/backups/homecontrol-heartbeat/app-rollback-{artifact.release}" if artifact else "/var/backups/homecontrol-heartbeat/homecontrol-deploy-rollback"
        return [
            AdapterStep("app_backup_present", f"sudo -n test -d {backup_dir}"),
            AdapterStep("rollback_heartbeat_app", f"sudo sh -c 'set -e; b={backup_dir}; systemctl stop hcm-heartbeat.service; [ -e \"$b/hcm_heartbeat.py\" ] && install -m 755 \"$b/hcm_heartbeat.py\" /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py; [ -e \"$b/homecontrol_identity.py\" ] && install -m 644 \"$b/homecontrol_identity.py\" /usr/local/lib/hcm-heartbeat/homecontrol_identity.py; [ -e \"$b/hcm-heartbeat\" ] && install -m 755 \"$b/hcm-heartbeat\" /usr/local/bin/hcm-heartbeat; [ -e \"$b/hcm-heartbeat.service\" ] && install -m 644 \"$b/hcm-heartbeat.service\" /etc/systemd/system/hcm-heartbeat.service; systemctl daemon-reload; systemctl restart hcm-heartbeat.service'", changes_system=True, timeout=120),
            AdapterStep("verify_heartbeat", self._heartbeat_service_command(), timeout=60),
        ]

    def _heartbeat_endpoint_snippet(self) -> str:
        return (
            "import json\n"
            "c=json.load(open('/etc/hcm-heartbeat/config.json'))\n"
            "addr=c.get('bind_address') or c.get('advertise_ip')\n"
            "if addr in ('0.0.0.0','::',''):\n"
            " addr=c.get('advertise_ip')\n"
            "port=int(c.get('port',6004))\n"
            "if not addr or addr in ('0.0.0.0','::'):\n"
            " raise SystemExit('heartbeat endpoint is ambiguous: bind_address={} advertise_ip={}'.format(c.get('bind_address'), c.get('advertise_ip')))\n"
            "endpoint='http://{}:{}'.format(addr,port)\n"
        )

    def _heartbeat_service_command(self) -> str:
        return (
            "systemctl is-active --quiet hcm-heartbeat.service && sudo -n python3 - <<'PY'\n"
            "import socket, urllib.request\n"
            + self._heartbeat_endpoint_snippet() +
            "s=socket.create_connection((addr,port),timeout=3)\n"
            "s.close()\n"
            "with urllib.request.urlopen(endpoint + '/status', timeout=5) as r:\n"
            " status=r.getcode()\n"
            "assert status == 200, status\n"
            "print('heartbeat_endpoint={} tcp=reachable http_status=200'.format(endpoint))\n"
            "PY"
        )

    def _heartbeat_verify_command(self, *, script: str) -> str:
        status_script = str(Path(script).with_name("heartbeat_status_verify.py"))
        return (
            "endpoint=$(sudo -n python3 - <<'PY'\n"
            + self._heartbeat_endpoint_snippet() +
            "print(endpoint)\n"
            "PY\n"
            f") && HC_HEARTBEAT_DB=/var/lib/hcm-heartbeat/registry.sqlite3 {script} \"$endpoint\" && "
            f"sudo -n python3 {status_script} \"$endpoint\" --grace 5"
        )


class JetsonDockerAdapter(BaseAdapter):
    adapter_name = "hcm_docker"

    def steps(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        image = f"homecontrol-hcm:{artifact.release}"
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_docker_layout", self._docker_preflight_command()),
            AdapterStep("build_hcm_image", f"sudo docker build -t {image} -f {release_dir}/06_config/01_HCM/Dockerfile.live {release_dir}", changes_system=True, timeout=600),
            AdapterStep("replace_hcm_container", f"sudo python3 {release_dir}/10_scripts/hcm_docker_deploy.py deploy --image {image}", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", self._hcm_health_command(), timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def _docker_preflight_command(self) -> str:
        return (
            "systemctl cat hcm.service >/dev/null && "
            "sudo -n docker network inspect hcm-control >/dev/null && "
            "sudo -n docker network inspect hcm-internal >/dev/null && "
            "sudo -n python3 - <<'PY'\n"
            "import json,subprocess\n"
            "def inspect(name):\n"
            " p=subprocess.Popen(['docker','inspect',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n"
            " out,err=p.communicate()\n"
            " if p.returncode != 0:\n"
            "  raise SystemExit(err.decode('utf-8','replace'))\n"
            " return json.loads(out.decode('utf-8'))[0]\n"
            "h=inspect('hcm-test')\n"
            "p=inspect('hcm-postgres')\n"
            "nets=set(h['NetworkSettings']['Networks'])\n"
            "assert {'hcm-control','hcm-internal'} <= nets, nets\n"
            "ports=h['HostConfig'].get('PortBindings') or {}\n"
            "assert '8080/tcp' in ports, ports\n"
            "assert h['Config'].get('Cmd') or h['Config'].get('Entrypoint'), 'missing startup command'\n"
            "mounts={(m.get('Source'),m.get('Destination')) for m in p.get('Mounts',[])}\n"
            "assert ('/srv/hcm-data/postgres','/var/lib/postgresql/data') in mounts, mounts\n"
            "assert any(m.get('Source') == '/etc/hcm/postgres-password' and m.get('Destination') == '/run/secrets/postgres_password' for m in p.get('Mounts',[])), 'missing postgres password mount'\n"
            "print('hcm_env_count={} hcm_mounts={} hcm_networks={} postgres_storage=ok postgres_secret_mount=ok cmd_present=true'.format(len(h['Config'].get('Env') or []), len(h.get('Mounts') or []), ','.join(sorted(nets))))\n"
            "PY"
        )

    def _hcm_endpoint_snippet(self) -> str:
        return (
            "import json, subprocess\n"
            "def inspect(name):\n"
            " p=subprocess.Popen(['docker','inspect',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n"
            " out,err=p.communicate()\n"
            " if p.returncode != 0:\n"
            "  raise SystemExit(err.decode('utf-8','replace'))\n"
            " return json.loads(out.decode('utf-8'))[0]\n"
            "h=inspect('hcm-test')\n"
            "bindings=(h.get('HostConfig') or {}).get('PortBindings') or {}\n"
            "published=[]\n"
            "for item in bindings.get('8080/tcp') or []:\n"
            " host=item.get('HostIp') or ''\n"
            " port=item.get('HostPort') or ''\n"
            " if host in ('','0.0.0.0','::') or not port:\n"
            "  continue\n"
            " published.append((host,port))\n"
            "if len(published) != 1:\n"
            " raise SystemExit('expected one concrete 8080/tcp binding, found {}'.format(bindings.get('8080/tcp')))\n"
            "host,port=published[0]\n"
            "url='http://{}:{}/api/v1/health'.format(host,port)\n"
        )

    def _hcm_health_command(self) -> str:
        return (
            "systemctl is-active --quiet hcm.service && "
            "sudo -n docker ps --format '{{.Names}}' | grep -qx hcm-test && "
            "sudo -n docker ps --format '{{.Names}}' | grep -qx hcm-postgres && "
            "sudo -n python3 - <<'PY' && "
            "systemctl is-active --quiet hcm-watchdog.timer && "
            "systemctl is-active --quiet hcm-heartbeat.service\n"
            "import urllib.request\n"
            + self._hcm_endpoint_snippet() +
            "with urllib.request.urlopen(url, timeout=5) as r:\n"
            " status=r.getcode()\n"
            "assert status == 200, status\n"
            "print('hcm_api_endpoint={} http_status=200'.format(url))\n"
            "PY"
        )

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("hcm_systemd_unit", "systemctl cat hcm.service && systemctl is-enabled hcm.service || true"),
            AdapterStep("hcm_docker_layout", self._docker_preflight_command()),
            AdapterStep("hcm_health", self._hcm_health_command()),
            AdapterStep("hcm_no_db_migration", "test -d /srv/hcm-data/postgres && sudo -n docker inspect hcm-postgres >/dev/null"),
        ]

    def no_change_health_steps(self) -> list[AdapterStep]:
        return [
            AdapterStep("hcm_docker_layout", self._docker_preflight_command()),
            AdapterStep("hcm_health", self._hcm_health_command()),
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
            AdapterStep("verify_hcm_api", self._hcm_health_command(), timeout=60),
        ]


class Lab1Adapter(BaseAdapter):
    adapter_name = "lab1_simulation"

    def steps(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        backup_dir = self._backup_dir(deployment_id or artifact.release)
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
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_lab1_safety", safety_check),
            AdapterStep("backup_lab_agent_components", self._lab1_backup_command(backup_dir), changes_system=True),
            AdapterStep("install_role_helper", f"sudo install -m 0755 {release_dir}/10_scripts/lab1_role_agent.py /opt/homecontrol-lab/lab1_role_agent.py", changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def release_marker(self) -> str:
        return "/opt/homecontrol-lab/state/homecontrol-release"

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("lab1_agent_layout", "python3 - <<'PY'\nimport os,socket\nassert socket.gethostname().split('.')[0] == 'lab1'\nfor p in ('/opt/homecontrol-lab/lab_agent.py','/opt/homecontrol-lab/lab1_role_agent.py','/opt/homecontrol-lab/state/module.json'):\n assert os.path.isfile(p), p\nprint('lab1_layout=ok')\nPY"),
            AdapterStep("lab1_state_safety", "python3 - <<'PY'\nimport json\ns=json.load(open('/opt/homecontrol-lab/state/module.json'))\nassert s.get('device_id') == '2ccf675d3414'\nassert s.get('hostname') == 'lab1'\nassert s.get('simulation') is True\nassert s.get('physical_outputs_enabled') is False\nassert 'role' in s\nPY"),
            AdapterStep("lab1_services", self._lab_services_command()),
            AdapterStep("lab1_heartbeat_client", self._lab_heartbeat_client_command()),
        ]

    def no_change_health_steps(self) -> list[AdapterStep]:
        return [
            AdapterStep("lab1_state_safety", "python3 - <<'PY'\nimport json\ns=json.load(open('/opt/homecontrol-lab/state/module.json'))\nassert s.get('simulation') is True\nassert s.get('physical_outputs_enabled') is False\nPY"),
            AdapterStep("lab1_services", self._lab_services_command()),
            AdapterStep("lab1_heartbeat_client", self._lab_heartbeat_client_command()),
        ]

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        backup_dir = self._backup_dir(artifact.release) if artifact else "/opt/homecontrol-lab/backups/homecontrol-deploy-rollback"
        return [
            AdapterStep("restore_role_helper", self._lab1_restore_command(backup_dir), changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
        ]

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        backup_dir = self._backup_dir(deployment_id or artifact.release)
        return self._run_rollback_steps(
            transport,
            [
                AdapterStep("restore_role_helper", self._lab1_restore_command(backup_dir), changes_system=True),
                AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
                AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
                AdapterStep("verify_lab_heartbeat_client", self._lab_heartbeat_client_command(), timeout=60),
            ],
        )

    def _backup_dir(self, deployment_id: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in deployment_id)
        return f"/opt/homecontrol-lab/backups/{safe}"

    def _lab1_backup_command(self, backup_dir: str) -> str:
        marker = self.release_marker()
        return (
            "sudo sh -c 'set -eu; "
            f"b={backup_dir}; marker={marker}; "
            "install -d -m 0755 /opt/homecontrol-lab/backups; "
            "[ ! -e \"$b\" ] || { echo backup_exists:$b >&2; exit 1; }; "
            "install -d -m 0755 \"$b\"; "
            "cp -a /opt/homecontrol-lab/lab1_role_agent.py \"$b/lab1_role_agent.py\"; "
            "if [ -f \"$marker\" ]; then cp -a \"$marker\" \"$b/homecontrol-release\"; else : > \"$b/homecontrol-release.absent\"; fi; "
            "stat -c \"%U:%G %a %n\" /opt/homecontrol-lab/lab1_role_agent.py \"$b/lab1_role_agent.py\" > \"$b/manifest.txt\"; "
            "cmp -s /opt/homecontrol-lab/lab1_role_agent.py \"$b/lab1_role_agent.py\"; "
            "ln -sfn \"$b\" /opt/homecontrol-lab/backups/homecontrol-deploy-rollback; "
            "echo lab1_backup=$b verified=true'"
        )

    def _lab1_restore_command(self, backup_dir: str) -> str:
        marker = self.release_marker()
        return (
            "sudo sh -c 'set -eu; "
            f"b={backup_dir}; marker={marker}; "
            "[ -d \"$b\" ] || { echo missing_backup:$b >&2; exit 1; }; "
            "[ -f \"$b/lab1_role_agent.py\" ] || { echo missing_role_backup >&2; exit 1; }; "
            "cp -a \"$b/lab1_role_agent.py\" /opt/homecontrol-lab/lab1_role_agent.py; "
            "if [ -f \"$b/homecontrol-release\" ]; then cp -a \"$b/homecontrol-release\" \"$marker\"; "
            "elif [ -f \"$b/homecontrol-release.absent\" ]; then rm -f \"$marker\"; "
            "else echo missing_marker_backup >&2; exit 1; fi; "
            "echo lab1_restore=$b marker_restored=true'"
        )

    def _lab_services_command(self) -> str:
        return (
            "python3 - <<'PY'\n"
            "import os, subprocess, sys\n"
            "required=('homecontrol-lab.service','hcm-heartbeat.service')\n"
            "failed=[]\n"
            "for svc in required:\n"
            " p=subprocess.Popen(['systemctl','is-active',svc],stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n"
            " out,err=p.communicate()\n"
            " state=out.decode('utf-8','replace').strip() or err.decode('utf-8','replace').strip() or 'unknown'\n"
            " if p.returncode != 0 or state != 'active':\n"
            "  failed.append('{} is {}'.format(svc,state))\n"
            " else:\n"
            "  print('{}=active'.format(svc))\n"
            " p=subprocess.Popen(['systemctl','show','-p','SubState','--value',svc],stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n"
            " out,err=p.communicate()\n"
            " sub=out.decode('utf-8','replace').strip()\n"
            " if p.returncode == 0 and sub:\n"
            "  print('{} substate={}'.format(svc,sub))\n"
            "sock='/run/hcm-heartbeat/control.sock'\n"
            "print('heartbeat_control_socket={}'.format('present' if os.path.exists(sock) else 'absent'))\n"
            "if failed:\n"
            " raise SystemExit('; '.join(failed))\n"
            "PY"
        )

    def _lab_heartbeat_client_command(self) -> str:
        return (
            "sudo -n python3 - <<'PY'\n"
            "import json, socket\n"
            "cfg=json.load(open('/etc/hcm-heartbeat/config.json'))\n"
            "assert cfg.get('role') == 'device', cfg.get('role')\n"
            "assert cfg.get('heartbeat_auth_mode') == 'hmac-sha256'\n"
            "addr=cfg.get('conflict_address') or cfg.get('conflict_hostname')\n"
            "port=int(cfg.get('port',6004))\n"
            "if not addr:\n"
            " raise SystemExit('missing conflict heartbeat destination')\n"
            "s=socket.create_connection((addr,port),timeout=3)\n"
            "s.close()\n"
            "print('heartbeat_destination={}:{} tcp=reachable auth_mode=hmac-sha256 control_socket=optional'.format(addr,port))\n"
            "PY"
        )


def adapter_for(entry: DeviceInventoryEntry) -> BaseAdapter:
    if entry.live_adapter == "conflict_heartbeat":
        return ConflictAdapter(entry)
    if entry.live_adapter == "hcm_docker":
        return JetsonDockerAdapter(entry)
    if entry.live_adapter == "lab1_simulation":
        return Lab1Adapter(entry)
    raise AdapterError(f"unsupported live adapter {entry.live_adapter!r}")
