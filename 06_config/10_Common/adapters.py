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
                    detail = step.command
                else:
                    result = transport.execute(self.entry.ssh_alias, step.command, timeout=step.timeout, step_name=step.name)
                    detail = result.stdout.strip() or step.command
            except Exception as exc:
                executed.append(
                    {"name": step.name, "status": "FAIL", "detail": str(exc), "changes_system": step.changes_system}
                )
                if changed and self.framework_rollback_needed(step, exc):
                    rollback = self.rollback_after_failure(transport, artifact, deployment_id=deployment_id)
                    executed.extend({"rollback": True, **item} for item in rollback.steps)
                    if rollback.status == "PASS":
                        return AdapterResult(target=self.entry.name, status="ROLLED BACK", steps=executed)
                return AdapterResult(target=self.entry.name, status="FAIL", steps=executed)
            if step.changes_system:
                changed = True
            executed.append(
                {"name": step.name, "status": "PASS", "detail": detail, "changes_system": step.changes_system}
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

    def rollback_for_deployment(self, transport: SSHTransport, deployment_id: str, release: str) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps_for_deployment(deployment_id, release))

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        return self._run_rollback_steps(transport, self.rollback_steps(artifact))

    def framework_rollback_needed(self, step: AdapterStep, exc: Exception) -> bool:
        return True

    def rollback_steps_for_deployment(self, deployment_id: str, release: str) -> list[AdapterStep]:
        artifact = ReleaseArtifact(release=release, path=Path("/tmp/homecontrol-manual-rollback.tar.gz"), sha256="manual", metadata_path=Path("/tmp/homecontrol-manual-rollback.json"))
        return self.rollback_steps(artifact)

    def safety_gate_steps(self, artifact: ReleaseArtifact, deployment_id: str) -> list[AdapterStep]:
        return []

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
        backup_dir = self._backup_dir(deployment_id or artifact.release)
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_auth", "sudo -n python3 - <<'PY'\nimport json,os,stat\ncfg=json.load(open('/etc/hcm-heartbeat/config.json'))\nassert cfg.get('heartbeat_auth_mode') == 'hmac-sha256'\npath=cfg.get('heartbeat_auth_secret_file')\nassert path and os.path.exists(path)\nmode=stat.S_IMODE(os.stat(path).st_mode)\nassert mode == 0o600, oct(mode)\nprint('auth_mode=hmac-sha256 secret_present=true secret_mode=0600')\nPY"),
            AdapterStep("backup_heartbeat_app", self._conflict_backup_command(backup_dir, release_dir), changes_system=True, timeout=120),
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
        backup_dir = self._backup_dir(artifact.release) if artifact else "/var/backups/homecontrol-heartbeat/homecontrol-deploy-rollback"
        verify = self._heartbeat_verify_command(script=f"{self.release_dir(artifact)}/10_scripts/heartbeat_verify_readonly.sh") if artifact else self._heartbeat_service_command()
        return [
            AdapterStep("app_backup_present", f"sudo -n test -d {backup_dir}"),
            AdapterStep("rollback_heartbeat_app", self._conflict_restore_command(backup_dir), changes_system=True, timeout=120),
            AdapterStep("verify_heartbeat", verify, timeout=60),
        ]

    def rollback_steps_for_deployment(self, deployment_id: str, release: str) -> list[AdapterStep]:
        backup_dir = self._backup_dir(deployment_id)
        release_dir = f"/tmp/homecontrol-release-{release}"
        return [
            AdapterStep("app_backup_present", f"sudo -n test -d {backup_dir}"),
            AdapterStep("rollback_heartbeat_app", self._conflict_restore_command(backup_dir), changes_system=True, timeout=120),
            AdapterStep("verify_heartbeat", self._heartbeat_verify_command(script=f"{release_dir}/10_scripts/heartbeat_verify_readonly.sh"), timeout=60),
        ]

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        backup_dir = self._backup_dir(deployment_id or artifact.release)
        return self._run_rollback_steps(
            transport,
            [
                AdapterStep("app_backup_present", f"sudo -n test -d {backup_dir}"),
                AdapterStep("rollback_heartbeat_app", self._conflict_restore_command(backup_dir), changes_system=True, timeout=120),
                AdapterStep("verify_heartbeat", self._heartbeat_verify_command(script=f"{self.release_dir(artifact)}/10_scripts/heartbeat_verify_readonly.sh"), timeout=60),
            ],
        )

    def safety_gate_steps(self, artifact: ReleaseArtifact, deployment_id: str) -> list[AdapterStep]:
        backup_dir = self._backup_dir(deployment_id)
        return [
            AdapterStep("heartbeat_backup_available", f"! sudo -n test -e {backup_dir}"),
            AdapterStep("heartbeat_backup_prereqs", "sudo -n test -r /etc/hcm-heartbeat/config.json && sudo -n test -f /var/lib/hcm-heartbeat/registry.sqlite3 && sudo -n test -r /var/lib/hcm-heartbeat/registry.sqlite3 && sudo -n test -x /usr/local/bin/hcm-heartbeat && sudo -n test -r /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py && sudo -n test -r /usr/local/lib/hcm-heartbeat/homecontrol_identity.py && sudo -n test -r /etc/systemd/system/hcm-heartbeat.service && sudo -n sh -c '[ -d /var/backups/homecontrol-heartbeat ] || [ -w /var/backups ]'"),
            AdapterStep("heartbeat_backup_storage", "df -Pk /var/backups | awk 'NR==2 { print \"available_kb=\"$4; if ($4 < 10240) exit 1 }'"),
            AdapterStep("heartbeat_registry_integrity", "sudo -n python3 - <<'PY'\nimport sqlite3\nconn=sqlite3.connect('file:/var/lib/hcm-heartbeat/registry.sqlite3?mode=ro', uri=True)\ntry:\n result=conn.execute('PRAGMA integrity_check').fetchone()[0]\n if result != 'ok':\n  raise SystemExit('registry integrity_check={}'.format(result))\n print('registry_integrity=ok')\nfinally:\n conn.close()\nPY"),
        ]

    def _backup_dir(self, deployment_id: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in deployment_id)
        return f"/var/backups/homecontrol-heartbeat/app-rollback-{safe}"

    def _conflict_backup_command(self, backup_dir: str, release_dir: str) -> str:
        marker = self.release_marker()
        return (
            "sudo sh -c 'set -eu; "
            f"b={backup_dir}; marker={marker}; "
            "[ ! -e \"$b\" ] || { echo backup_exists:$b >&2; exit 1; }; "
            "install -d -m 0755 /var/backups/homecontrol-heartbeat; "
            f"HC_HEARTBEAT_BACKUP_DIR=\"$b\" HC_HEARTBEAT_RELEASE_MARKER=\"$marker\" {release_dir}/10_scripts/heartbeat_backup.sh conflict >/tmp/homecontrol-heartbeat-backup-path; "
            "[ \"$(cat /tmp/homecontrol-heartbeat-backup-path)\" = \"$b\" ]; "
            "for f in hcm_heartbeat.py homecontrol_identity.py hcm-heartbeat hcm-heartbeat.service manifest.txt; do [ -e \"$b/$f\" ] || { echo incomplete_backup:$f >&2; exit 1; }; done; "
            "if [ -f \"$marker\" ]; then cmp -s \"$marker\" \"$b/homecontrol-release\"; else [ -f \"$b/homecontrol-release.absent\" ]; fi; "
            "ln -sfn \"$b\" /var/backups/homecontrol-heartbeat/homecontrol-deploy-rollback; "
            "echo heartbeat_backup=$b verified=true marker_preserved=true registry_snapshot=disaster_recovery_only'"
        )

    def _conflict_restore_command(self, backup_dir: str) -> str:
        marker = self.release_marker()
        return (
            "sudo sh -c 'set -eu; "
            f"b={backup_dir}; marker={marker}; "
            "[ -d \"$b\" ] || { echo missing_backup:$b >&2; exit 1; }; "
            "for f in hcm_heartbeat.py homecontrol_identity.py hcm-heartbeat hcm-heartbeat.service; do [ -e \"$b/$f\" ] || { echo incomplete_backup:$f >&2; exit 1; }; done; "
            "systemctl stop hcm-heartbeat.service; "
            "install -m 755 \"$b/hcm_heartbeat.py\" /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py; "
            "install -m 644 \"$b/homecontrol_identity.py\" /usr/local/lib/hcm-heartbeat/homecontrol_identity.py; "
            "install -m 755 \"$b/hcm-heartbeat\" /usr/local/bin/hcm-heartbeat; "
            "install -m 644 \"$b/hcm-heartbeat.service\" /etc/systemd/system/hcm-heartbeat.service; "
            "if [ -f \"$b/homecontrol-release\" ]; then install -d -m 0755 \"$(dirname \"$marker\")\"; cp -a \"$b/homecontrol-release\" \"$marker\"; "
            "elif [ -f \"$b/homecontrol-release.absent\" ]; then rm -f \"$marker\"; "
            "else echo missing_marker_backup >&2; exit 1; fi; "
            "systemctl daemon-reload; systemctl restart hcm-heartbeat.service; "
            "echo heartbeat_restore=$b marker_restored=true registry_preserved=true'"
        )

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
        rollback_name = self._rollback_container_name(deployment_id or artifact.release)
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_docker_layout", self._docker_preflight_command()),
            AdapterStep("build_hcm_image", f"sudo docker build -t {image} -f {release_dir}/06_config/01_HCM/Dockerfile.live {release_dir}", changes_system=True, timeout=600),
            AdapterStep("replace_hcm_container", f"sudo python3 {release_dir}/10_scripts/hcm_docker_deploy.py deploy --image {image} --rollback-name {rollback_name} --deployment-id {deployment_id or artifact.release}", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", self._hcm_health_command(), timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def _rollback_container_name(self, deployment_id: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in deployment_id).strip("-")
        return f"hcm-rollback-{safe}"

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
            rollback_name = self._rollback_container_name(artifact.release)
        else:
            helper = "/tmp/homecontrol-current/10_scripts/hcm_docker_deploy.py"
            rollback_name = "hcm-rollback-manual"
        return [
            AdapterStep("restore_previous_container", f"sudo python3 {helper} rollback --rollback-name {rollback_name}", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", self._hcm_health_command(), timeout=60),
        ]

    def rollback_steps_for_deployment(self, deployment_id: str, release: str) -> list[AdapterStep]:
        helper = f"/tmp/homecontrol-release-{release}/10_scripts/hcm_docker_deploy.py"
        rollback_name = self._rollback_container_name(deployment_id)
        return [
            AdapterStep("restore_previous_container", f"sudo python3 {helper} rollback --rollback-name {rollback_name}", changes_system=True, timeout=180),
            AdapterStep("verify_hcm_api", self._hcm_health_command(), timeout=60),
        ]

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        if not deployment_id:
            return AdapterResult(target=self.entry.name, status="FAIL", steps=[{"name": "rollback_context", "status": "FAIL", "detail": "missing deployment_id for Jetson rollback", "changes_system": False}])
        return self._run_rollback_steps(transport, self.rollback_steps_for_deployment(deployment_id, artifact.release))

    def framework_rollback_needed(self, step: AdapterStep, exc: Exception) -> bool:
        if step.name == "replace_hcm_container":
            return False
        return True

    def safety_gate_steps(self, artifact: ReleaseArtifact, deployment_id: str) -> list[AdapterStep]:
        rollback_name = self._rollback_container_name(deployment_id)
        return [
            AdapterStep("rollback_container_available", f"! sudo -n docker inspect {rollback_name} >/dev/null 2>&1"),
            AdapterStep("docker_replace_prereqs", "sudo -n docker inspect hcm-test >/dev/null && sudo -n docker inspect hcm-postgres >/dev/null && sudo -n docker network inspect hcm-control >/dev/null && sudo -n docker network inspect hcm-internal >/dev/null"),
            AdapterStep("docker_storage_available", "df -Pk /var/lib/docker | awk 'NR==2 { print \"available_kb=\"$4; if ($4 < 102400) exit 1 }'"),
        ]


class Lab1Adapter(BaseAdapter):
    adapter_name = "lab1_simulation"

    def steps(self, artifact: ReleaseArtifact, deployment_id: str | None = None) -> list[AdapterStep]:
        release_dir = self.release_dir(artifact)
        backup_dir = self._backup_dir(deployment_id or artifact.release)
        return super().steps(artifact, deployment_id=deployment_id) + [
            AdapterStep("preflight_lab1_safety", self._lab_state_safety_command()),
            AdapterStep("backup_lab_agent_components", self._lab1_backup_command(backup_dir), changes_system=True),
            AdapterStep("install_role_helper", f"sudo install -m 0755 {release_dir}/10_scripts/lab1_role_agent.py /opt/homecontrol-lab/lab1_role_agent.py", changes_system=True),
            AdapterStep("install_emergency_ui", self._lab1_emergency_install_command(release_dir), changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("restart_emergency_ui", "sudo systemctl daemon-reload && sudo systemctl enable --now homecontrol-lab-emergency.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_state_safety", self._lab_state_safety_command(backup_dir), timeout=60),
            AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
            AdapterStep("verify_emergency_ui", self._lab1_emergency_verify_command(), timeout=60),
            AdapterStep("verify_lab_heartbeat_client", self._lab_heartbeat_client_command(), timeout=60),
            AdapterStep("record_release", f"printf '%s\\n' {artifact.release} | sudo tee {self.release_marker()} >/dev/null", changes_system=True),
        ]

    def release_marker(self) -> str:
        return "/opt/homecontrol-lab/state/homecontrol-release"

    def preflight_steps(self) -> list[AdapterStep]:
        return super().preflight_steps() + [
            AdapterStep("lab1_agent_layout", "python3 - <<'PY'\nimport os,socket\nassert socket.gethostname().split('.')[0] == 'lab1'\nfor p in ('/opt/homecontrol-lab/lab_agent.py','/opt/homecontrol-lab/lab1_role_agent.py','/opt/homecontrol-lab/state/module.json'):\n assert os.path.isfile(p), p\nprint('lab1_layout=ok')\nPY"),
            AdapterStep("lab1_state_safety", self._lab_state_safety_command()),
            AdapterStep("lab1_services", self._lab_services_command()),
            AdapterStep("emergency_ui_service", "sudo -n systemctl is-active homecontrol-lab-emergency.service && sudo -n ss -ltn '( sport = :6010 )' || true"),
            AdapterStep("lab1_heartbeat_client", self._lab_heartbeat_client_command()),
        ]

    def safety_gate_steps(self, artifact: ReleaseArtifact, deployment_id: str) -> list[AdapterStep]:
        backup_dir = self._backup_dir(deployment_id)
        return [
            AdapterStep("lab1_backup_prereqs", "sudo -n test -f /opt/homecontrol-lab/lab1_role_agent.py && sudo -n test -r /opt/homecontrol-lab/lab1_role_agent.py && sudo -n test -d /opt/homecontrol-lab && sudo -n test -w /opt/homecontrol-lab"),
            AdapterStep("lab1_backup_unique", f"! sudo -n test -e {backup_dir}"),
            AdapterStep("lab1_backup_storage", "df -Pk /opt/homecontrol-lab | awk 'NR==2 { print \"available_kb=\"$4; if ($4 < 10240) exit 1 }'"),
        ]

    def no_change_health_steps(self) -> list[AdapterStep]:
        return [
            AdapterStep("lab1_state_safety", self._lab_state_safety_command()),
            AdapterStep("lab1_services", self._lab_services_command()),
            AdapterStep("lab1_heartbeat_client", self._lab_heartbeat_client_command()),
        ]

    def rollback_steps(self, artifact: ReleaseArtifact | None = None) -> list[AdapterStep]:
        backup_dir = self._backup_dir(artifact.release) if artifact else "/opt/homecontrol-lab/backups/homecontrol-deploy-rollback"
        return [
            AdapterStep("restore_role_helper", self._lab1_restore_command(backup_dir), changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_state_safety", self._lab_state_safety_command(backup_dir), timeout=60),
            AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
            AdapterStep("verify_lab_heartbeat_client", self._lab_heartbeat_client_command(), timeout=60),
        ]

    def rollback_steps_for_deployment(self, deployment_id: str, release: str) -> list[AdapterStep]:
        backup_dir = self._backup_dir(deployment_id)
        return [
            AdapterStep("restore_role_helper", self._lab1_restore_command(backup_dir), changes_system=True),
            AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
            AdapterStep("verify_lab_state_safety", self._lab_state_safety_command(backup_dir), timeout=60),
            AdapterStep("verify_lab_services", self._lab_services_command(), timeout=60),
            AdapterStep("verify_lab_heartbeat_client", self._lab_heartbeat_client_command(), timeout=60),
        ]

    def rollback_after_failure(self, transport: SSHTransport, artifact: ReleaseArtifact, deployment_id: str | None = None) -> AdapterResult:
        backup_dir = self._backup_dir(deployment_id or artifact.release)
        return self._run_rollback_steps(
            transport,
            [
                AdapterStep("restore_role_helper", self._lab1_restore_command(backup_dir), changes_system=True),
                AdapterStep("restart_lab_agent", "sudo systemctl restart homecontrol-lab.service", changes_system=True, timeout=60),
                AdapterStep("verify_lab_state_safety", self._lab_state_safety_command(backup_dir), timeout=60),
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
            "for f in /opt/homecontrol-lab/lab1_emergency.py /etc/systemd/system/homecontrol-lab-emergency.service; do if [ -e \"$f\" ]; then cp -a \"$f\" \"$b/$(basename \"$f\")\"; fi; done; "
            "if [ -f /opt/homecontrol-lab/module_infra.py ]; then cp -a /opt/homecontrol-lab/module_infra.py \"$b/module_infra.py\"; fi; "
            "if [ -d /opt/homecontrol-lab/state/homecontrol ]; then cp -a /opt/homecontrol-lab/state/homecontrol \"$b/homecontrol\"; fi; "
            "cp -a /opt/homecontrol-lab/state/module.json \"$b/module.json\"; "
            "if [ -f \"$marker\" ]; then cp -a \"$marker\" \"$b/homecontrol-release\"; else : > \"$b/homecontrol-release.absent\"; fi; "
            "stat -c \"%U:%G %a %n\" /opt/homecontrol-lab/lab1_role_agent.py \"$b/lab1_role_agent.py\" /opt/homecontrol-lab/state/module.json \"$b/module.json\" > \"$b/manifest.txt\"; "
            "cmp -s /opt/homecontrol-lab/lab1_role_agent.py \"$b/lab1_role_agent.py\"; "
            "cmp -s /opt/homecontrol-lab/state/module.json \"$b/module.json\"; "
            "ln -sfn \"$b\" /opt/homecontrol-lab/backups/homecontrol-deploy-rollback; "
            "echo lab1_backup=$b verified=true'"
        )

    def _lab1_emergency_install_command(self, release_dir: str) -> str:
        return (
            f"sudo install -m 0755 {release_dir}/10_scripts/lab1_emergency.py /opt/homecontrol-lab/lab1_emergency.py && "
            f"sudo install -m 0644 {release_dir}/06_config/08_LAB/homecontrol-lab-emergency.service /etc/systemd/system/homecontrol-lab-emergency.service && "
            f"sudo install -m 0644 {release_dir}/07_servises/common/module_infra.py /opt/homecontrol-lab/module_infra.py && "
            "sudo install -d -m 0750 -o root -g root /opt/homecontrol-lab/state/homecontrol/config/LCM && "
            "sudo /usr/bin/python3 - <<'PY'\n"
            "from pathlib import Path\nimport json, secrets, os, sys, importlib\n"
            "sys.path.insert(0, '/opt/homecontrol-lab')\n"
            "LocalAuthStore=importlib.import_module('module_infra').LocalAuthStore\n"
            "auth=Path('/opt/homecontrol-lab/state/homecontrol/config/LCM/lab1.auth.json')\n"
            "bootstrap=Path('/opt/homecontrol-lab/state/homecontrol/local-admin-bootstrap.txt')\n"
            "if not auth.exists():\n"
            " password=secrets.token_urlsafe(24)\n"
            " auth.parent.mkdir(parents=True, exist_ok=True)\n"
            " auth.write_text(json.dumps({'users':[{'username':'admin','role':'ADMIN',**LocalAuthStore.hash_password(password)}]}, indent=2)+'\\n')\n"
            " os.chmod(auth, 0o600)\n"
            " bootstrap.write_text('username=admin\\npassword='+password+'\\n')\n"
            " os.chmod(bootstrap, 0o600)\n"
            " print('local_admin_provisioned=true credential_file='+str(bootstrap))\n"
            "else:\n"
            " print('local_admin_provisioned=false existing_credentials_preserved=true')\n"
            "PY"
        )

    def _lab1_emergency_verify_command(self) -> str:
        return (
            "python3 - <<'PY'\n"
            "import json, urllib.request\n"
            "state=json.load(open('/opt/homecontrol-lab/state/module.json'))\n"
            "assert state.get('device_id') == '2ccf675d3414'\n"
            "assert state.get('simulation') is True\n"
            "assert state.get('physical_outputs_enabled') is False\n"
            "health=json.load(urllib.request.urlopen('http://127.0.0.1:6010/health', timeout=5))\n"
            "identity=health.get('identity',{})\n"
            "assert identity.get('device_id') == '2ccf675d3414'\n"
            "assert identity.get('role') == state.get('role')\n"
            "assert identity.get('simulation') is True\n"
            "assert identity.get('physical_outputs_enabled') is False\n"
            "print('emergency_ui=healthy port=6010 local_auth_required=true physical_outputs_enabled=false')\n"
            "PY"
        )

    def _lab1_restore_command(self, backup_dir: str) -> str:
        marker = self.release_marker()
        return (
            "sudo sh -c 'set -eu; "
            f"b={backup_dir}; marker={marker}; "
            "[ -d \"$b\" ] || { echo missing_backup:$b >&2; exit 1; }; "
            "[ -f \"$b/lab1_role_agent.py\" ] || { echo missing_role_backup >&2; exit 1; }; "
            "cp -a \"$b/lab1_role_agent.py\" /opt/homecontrol-lab/lab1_role_agent.py; "
            "if [ -f \"$b/lab1_emergency.py\" ]; then cp -a \"$b/lab1_emergency.py\" /opt/homecontrol-lab/lab1_emergency.py; else rm -f /opt/homecontrol-lab/lab1_emergency.py; fi; "
            "if [ -f \"$b/homecontrol-lab-emergency.service\" ]; then cp -a \"$b/homecontrol-lab-emergency.service\" /etc/systemd/system/homecontrol-lab-emergency.service; else rm -f /etc/systemd/system/homecontrol-lab-emergency.service; fi; "
            "if [ -f \"$b/module_infra.py\" ]; then cp -a \"$b/module_infra.py\" /opt/homecontrol-lab/module_infra.py; else rm -f /opt/homecontrol-lab/module_infra.py; fi; "
            "sudo systemctl daemon-reload; sudo systemctl disable --now homecontrol-lab-emergency.service || true; "
            "if [ -f \"$b/homecontrol-release\" ]; then cp -a \"$b/homecontrol-release\" \"$marker\"; "
            "elif [ -f \"$b/homecontrol-release.absent\" ]; then rm -f \"$marker\"; "
            "else echo missing_marker_backup >&2; exit 1; fi; "
            "echo lab1_restore=$b marker_restored=true'"
        )

    def _lab_state_safety_command(self, backup_dir: str | None = None) -> str:
        backup_state = f"{backup_dir}/module.json" if backup_dir else ""
        return (
            "python3 - <<'PY'\n"
            "import json, os, socket\n"
            "state_path='/opt/homecontrol-lab/state/module.json'\n"
            f"backup_state={backup_state!r}\n"
            "try:\n"
            " with open(state_path) as f:\n"
            "  state=json.load(f)\n"
            "except Exception as exc:\n"
            " raise SystemExit('module_state_invalid: {}'.format(exc))\n"
            "host=socket.gethostname().split('.')[0]\n"
            "if host != 'lab1':\n"
            " raise SystemExit('hostname {} != lab1'.format(host))\n"
            "if state.get('device_id') != '2ccf675d3414':\n"
            " raise SystemExit('device_id {} != 2ccf675d3414'.format(state.get('device_id')))\n"
            "if state.get('hostname') != 'lab1':\n"
            " raise SystemExit('state hostname {} != lab1'.format(state.get('hostname')))\n"
            "if state.get('simulation') is not True:\n"
            " raise SystemExit('simulation is not true')\n"
            "if state.get('physical_outputs_enabled') is not False:\n"
            " raise SystemExit('physical_outputs_enabled is not false')\n"
            "if 'role' not in state:\n"
            " raise SystemExit('role missing')\n"
            "if backup_state:\n"
            " if not os.path.isfile(backup_state):\n"
            "  raise SystemExit('backup module_state missing: {}'.format(backup_state))\n"
            " try:\n"
            "  with open(backup_state) as f:\n"
            "   previous=json.load(f)\n"
            " except Exception as exc:\n"
            "  raise SystemExit('backup_module_state_invalid: {}'.format(exc))\n"
            " for key in ('role','device_id','hostname','simulation','physical_outputs_enabled'):\n"
            "  if previous.get(key) != state.get(key):\n"
            "   raise SystemExit('{} changed: {!r} != {!r}'.format(key,state.get(key),previous.get(key)))\n"
            "print('lab1_state_safety=ok hostname=lab1 device_id=2ccf675d3414 simulation=true physical_outputs_enabled=false role={}'.format(state.get('role')))\n"
            "PY"
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
            "import json, socket, time\n"
            "try:\n"
            " import urllib.request as urllib_request\n"
            "except ImportError:\n"
            " import urllib2 as urllib_request\n"
            "cfg=json.load(open('/etc/hcm-heartbeat/config.json'))\n"
            "assert cfg.get('role') == 'device', cfg.get('role')\n"
            "assert cfg.get('heartbeat_auth_mode') == 'hmac-sha256'\n"
            "assert cfg.get('device_id') in (None, '2ccf675d3414')\n"
            "bind=cfg.get('bind_address') or '127.0.0.1'\n"
            "status_host='127.0.0.1' if bind in ('0.0.0.0','::','') else bind\n"
            "addr=cfg.get('conflict_address') or cfg.get('conflict_hostname')\n"
            "port=int(cfg.get('port',6004))\n"
            "if not addr:\n"
            " raise SystemExit('missing conflict heartbeat destination')\n"
            "s=socket.create_connection((addr,port),timeout=3)\n"
            "s.close()\n"
            "if ':' in status_host and not status_host.startswith('['):\n"
            " endpoint='http://[{}]:{}'.format(status_host,port)\n"
            "else:\n"
            " endpoint='http://{}:{}'.format(status_host,port)\n"
            "deadline=time.time()+30\n"
            "last_error='status not checked'\n"
            "while time.time() <= deadline:\n"
            " try:\n"
            "  response=urllib_request.urlopen(endpoint + '/status', timeout=5)\n"
            "  try:\n"
            "   code=response.getcode()\n"
            "   raw=response.read(65537)\n"
            "  finally:\n"
            "   close=getattr(response,'close',None)\n"
            "   if close:\n"
            "    close()\n"
            "  if code != 200:\n"
            "   raise ValueError('status HTTP {}'.format(code))\n"
            "  status=json.loads(raw.decode('utf-8'))\n"
            "  if status.get('device_id') != '2ccf675d3414':\n"
            "   raise ValueError('status device_id {} != 2ccf675d3414'.format(status.get('device_id')))\n"
            "  if str(status.get('hostname','')).split('.')[0] != 'lab1':\n"
            "   raise ValueError('status hostname {} != lab1'.format(status.get('hostname')))\n"
            "  peer=status.get('status',{}).get('peer',{})\n"
            "  if peer.get('enabled') is not True:\n"
            "   raise ValueError('heartbeat peer status not enabled')\n"
            "  if peer.get('online') is not True:\n"
            "   raise ValueError('heartbeat peer offline: {}'.format(peer.get('last_error')))\n"
            "  if peer.get('last_error') not in (None, ''):\n"
            "   raise ValueError('heartbeat peer error: {}'.format(peer.get('last_error')))\n"
            "  if peer.get('seconds_since_ack') is None:\n"
            "   raise ValueError('heartbeat has no ack age')\n"
            "  print('heartbeat_destination={}:{} tcp=reachable status_endpoint={} peer_online=true seconds_since_ack={} auth_mode=hmac-sha256 control_socket=optional'.format(addr,port,endpoint,peer.get('seconds_since_ack')))\n"
            "  break\n"
            " except Exception as exc:\n"
            "  last_error=str(exc)\n"
            "  if time.time() > deadline:\n"
            "   raise SystemExit('heartbeat_client_status_failed: {}'.format(last_error))\n"
            "  time.sleep(2)\n"
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
