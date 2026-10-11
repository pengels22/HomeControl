from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class TransportError(RuntimeError):
    pass


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
    completed = subprocess.run(
        command,
        input=input,
        timeout=timeout,
        text=False,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


class SSHTransport:
    def __init__(self, *, runner: Runner = subprocess_runner, connect_timeout: int = 10):
        self.runner = runner
        self.connect_timeout = connect_timeout

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

    def execute(self, alias: str, command: str, *, timeout: int = 60) -> CommandResult:
        result = self.runner(self._ssh_base() + [alias, "sh", "-lc", command], timeout=timeout)
        if result.returncode != 0:
            raise TransportError(_format_failure("ssh command failed", result))
        return result

    def transfer_file(self, alias: str, local: Path, remote: str, *, timeout: int = 120) -> CommandResult:
        if not local.is_file():
            raise TransportError(f"artifact does not exist: {local}")
        result = self.runner(self._scp_base() + [str(local), f"{alias}:{remote}"], timeout=timeout)
        if result.returncode != 0:
            raise TransportError(_format_failure("scp transfer failed", result))
        return result


def _format_failure(prefix: str, result: CommandResult) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit {result.returncode}"
    return f"{prefix}: {detail}"
