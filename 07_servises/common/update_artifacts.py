"""Verification and execution policy for module update artifacts.

The wire protocol may identify an artifact, but it never supplies an executable
or an argument vector.  Installers are selected from this fixed registry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedArtifact:
    artifact_id: str
    target_module: str
    hardware_revision: str
    version: str
    path: Path
    installer: str


# These commands are intentionally fixed.  A deployment can replace the
# scripts, but a request cannot select an arbitrary executable or arguments.
INSTALLERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("RCM", "firmware"): ("/usr/local/lib/homecontrol/install-rcm-firmware",),
    ("LCM", "firmware"): ("/usr/local/lib/homecontrol/install-lcm-firmware",),
    ("SIM", "firmware"): ("/usr/local/lib/homecontrol/install-sim-firmware",),
    ("PNL", "firmware"): ("/usr/local/lib/homecontrol/install-pnl-firmware",),
}


def verify_ed25519(public_key: bytes, data: bytes, signature: bytes) -> None:
    """Verify an Ed25519 signature without carrying private key material."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except ImportError as exc:
        raise ArtifactError("Ed25519 verification dependency is unavailable") from exc


def _signed_body(artifact: dict[str, Any]) -> bytes:
    return json.dumps({k: v for k, v in artifact.items() if k != "signature"}, sort_keys=True, separators=(",", ":")).encode()


def verify_artifact(
    artifact: dict[str, Any],
    *,
    target_module: str,
    hardware_revision: str,
    trusted_public_key: bytes | None,
    staging_root: Path = Path('/var/lib/homecontrol/updates/staging'),
    signature_verifier: Callable[[bytes, bytes, bytes], None] | None = None,
) -> VerifiedArtifact:
    required = ("artifact_id", "target_module", "hardware_revision", "version", "path", "sha256", "installer", "signature")
    if any(not artifact.get(key) for key in required):
        raise ArtifactError("artifact is missing required signed metadata")
    if str(artifact["target_module"]).upper() != target_module.upper():
        raise ArtifactError("artifact target module mismatch")
    if str(artifact["hardware_revision"]) != hardware_revision:
        raise ArtifactError("artifact hardware revision mismatch")
    installer = str(artifact["installer"])
    if (target_module.upper(), installer) not in INSTALLERS:
        raise ArtifactError("artifact installer is not approved")
    if trusted_public_key is None:
        raise ArtifactError("signed update verification is not configured")
    signature_verifier = signature_verifier or verify_ed25519
    try:
        signature = base64.b64decode(str(artifact["signature"]), validate=True)
    except Exception as exc:
        raise ArtifactError("invalid artifact signature encoding") from exc
    try:
        signature_verifier(trusted_public_key, _signed_body(artifact), signature)
    except Exception as exc:
        raise ArtifactError("artifact signature verification failed") from exc
    path = Path(str(artifact["path"]))
    root = staging_root.resolve()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactError("artifact path is unavailable") from exc
    if path.is_symlink() or root not in resolved.parents or not resolved.is_file():
        raise ArtifactError("artifact path is outside the update staging directory")
    if not path.is_file():
        raise ArtifactError("artifact path is unavailable")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, str(artifact["sha256"]).lower()):
        raise ArtifactError("artifact checksum mismatch")
    return VerifiedArtifact(str(artifact["artifact_id"]), target_module.upper(), hardware_revision, str(artifact["version"]), resolved, installer)
