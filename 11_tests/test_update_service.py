import base64
import hashlib
import importlib

import pytest

policy = importlib.import_module('07_servises.common.update_artifacts')
service = importlib.import_module('07_servises.update_service')


def _artifact(tmp_path, **overrides):
    path = tmp_path / 'firmware.bin'
    path.write_bytes(b'approved image')
    item = {
        'artifact_id': 'artifact-1', 'target_module': 'RCM',
        'hardware_revision': 'RMC-NANO-ATMEGA328P', 'version': '1.2.3',
        'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'installer': 'firmware', 'signature': base64.b64encode(b'ok').decode(),
    }
    item.update(overrides)
    return item


def test_verified_artifact_requires_target_revision_hash_and_signature(tmp_path):
    artifact = _artifact(tmp_path)
    result = policy.verify_artifact(
        artifact, target_module='RCM', hardware_revision='RMC-NANO-ATMEGA328P',
        trusted_public_key=b'trusted', signature_verifier=lambda key, data, sig: None,
    )
    assert result.artifact_id == 'artifact-1'

    for field, value in [('target_module', 'LCM'), ('hardware_revision', 'other'), ('sha256', 'bad'), ('signature', '')]:
        bad = dict(artifact, **{field: value})
        with pytest.raises(policy.ArtifactError):
            policy.verify_artifact(
                bad, target_module='RCM', hardware_revision='RMC-NANO-ATMEGA328P',
                trusted_public_key=b'trusted', signature_verifier=lambda key, data, sig: None,
            )


def test_update_service_rejects_arbitrary_command_payload():
    assert service.artifact_policy.INSTALLERS[('RCM', 'firmware')]
