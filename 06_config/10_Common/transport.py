from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class TransportError(RuntimeError):
    pass


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        input: bytes | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        ...


def subprocess_runner(command: list[str], *, input: bytes | None = None, timeout: int | None = None) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            input=input,
            timeout=timeout,
            text=False,
            capture_output=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        if isinstance(stdout, str):
            stdout = stdout.encode()
        if isinstance(stderr, str):
            stderr = stderr.encode()
        stderr += b"\nconnection timed out during command execution"
        return CommandResult(
            command=command,
            returncode=255,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


def _sanitize_stream(value: str) -> str:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("tput: No value for $TERM"):
            continue
        if "post-quantum" in stripped.lower() and "warning" in stripped.lower():
            continue
        lowered = stripped.lower()
        if any(word in lowered for word in ("password", "secret", "private key", "token")):
            lines.append("[redacted sensitive output]")
        else:
            lines.append(stripped)
    text = "\n".join(lines)
    return text[:2000]


class SSHTransport:
    def __init__(self, *, runner: Runner = subprocess_runner, connect_timeout: int = 10, read_only_retries: int = 2):
        self.runner = runner
        self.connect_timeout = connect_timeout
        self.read_only_retries = read_only_retries

    def _ssh_base(self) -> list[str]:
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
        ]

    def _scp_base(self) -> list[str]:
        return [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
        ]

    def execute(
        self,
        alias: str,
        command: str,
        *,
        timeout: int = 60,
        step_name: str | None = None,
        read_only: bool = False,
    ) -> CommandResult:
        remote = f"TERM=dumb LC_ALL=C; export TERM LC_ALL; {command}"
        attempts = 1 + (self.read_only_retries if read_only else 0)
        last_result: CommandResult | None = None
        for attempt in range(1, attempts + 1):
            result = self.runner(self._ssh_base() + [alias, "sh", "-lc", remote], timeout=timeout)
            result = CommandResult(
                command=result.command,
                returncode=result.returncode,
                stdout=_sanitize_stream(result.stdout),
                stderr=_sanitize_stream(result.stderr),
            )
            if result.returncode == 0:
                if attempt > 1:
                    LOG.warning("read-only SSH command succeeded after retry target=%s step=%s attempt=%s", alias, step_name or "remote_command", attempt)
                return result
            last_result = result
            if not read_only or attempt == attempts or not _is_retryable_transport_failure(result):
                break
            LOG.warning(
                "retrying transient read-only SSH failure target=%s step=%s attempt=%s/%s detail=%s",
                alias,
                step_name or "remote_command",
                attempt,
                attempts,
                _format_failure(alias, step_name or "remote_command", result),
            )
        assert last_result is not None
        raise TransportError(_format_failure(alias, step_name or "remote_command", last_result))

    def transfer_file(self, alias: str, local: Path, remote: str, *, timeout: int = 120) -> CommandResult:
        if not local.is_file():
            raise TransportError(f"artifact does not exist: {local}")
        result = self.runner(self._scp_base() + [str(local), f"{alias}:{remote}"], timeout=timeout)
        if result.returncode != 0:
            raise TransportError(_format_failure(alias, "transfer_artifact", result))
        return result


def _format_failure(alias: str, step_name: str, result: CommandResult) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    parts = [
        f"target={alias}",
        f"step={step_name}",
        f"exit={result.returncode}",
    ]
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    if len(parts) == 3:
        parts.append("reason=command failed without output")
    return "; ".join(parts)


def _is_retryable_transport_failure(result: CommandResult) -> bool:
    if result.returncode != 255:
        return False
    text = f"{result.stdout}\n{result.stderr}".lower()
    retryable = (
        "connection timed out",
        "connection timeout",
        "operation timed out",
        "banner exchange",
        "connection to unknown port 65535 timed out",
        "connection closed by remote host",
        "proxyjump",
        "proxy command",
        "kex_exchange_identification",
    )
    security_failures = (
        "host key verification failed",
        "permission denied",
        "authentication failed",
        "bad permissions",
        "identification has changed",
    )
    return any(item in text for item in retryable) and not any(item in text for item in security_failures)
