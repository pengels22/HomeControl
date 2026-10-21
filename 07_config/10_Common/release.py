from __future__ import annotations

import re
import subprocess
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseError(ValueError):
    pass


def validate_release_sha(value: str) -> str:
    release = value.strip().lower()
    if not SHA_RE.fullmatch(release):
        raise ReleaseError("release must be a full 40-character Git commit SHA")
    return release


def current_git_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(result.stderr.strip() or "unable to resolve repository HEAD")
    return validate_release_sha(result.stdout)


def worktree_has_uncommitted_changes(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(result.stderr.strip() or "unable to inspect repository status")
    return bool(result.stdout.strip())


def resolve_release(repo_root: Path, release: str | None = None) -> str:
    if release:
        return validate_release_sha(release)
    return current_git_sha(repo_root)
