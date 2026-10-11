from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    from . import release as release_mod
except ImportError:
    import release as release_mod  # type: ignore


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseArtifact:
    release: str
    path: Path
    sha256: str
    metadata_path: Path


def create_release_artifact(repo_root: Path, release: str, output_dir: Path) -> ReleaseArtifact:
    release = release_mod.validate_release_sha(release)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"homecontrol-{release}.tar.gz"
    metadata = output_dir / f"homecontrol-{release}.json"
    result = subprocess.run(
        ["git", "archive", "--format=tar.gz", "-o", str(artifact), release],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ArtifactError(result.stderr.strip() or "git archive failed")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata.write_text(
        json.dumps(
            {
                "release": release,
                "artifact": artifact.name,
                "sha256": digest,
                "created_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return ReleaseArtifact(release=release, path=artifact, sha256=digest, metadata_path=metadata)
