import base64
import hashlib
import importlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

policy = importlib.import_module('07_servises.common.update_artifacts')
service = importlib.import_module('07_servises.update_service')


def _artifact(tmp_path, **overrides):
    staging = tmp_path / 'staging'
    staging.mkdir(exist_ok=True)
    path = staging / 'firmware.bin'
    path.write_bytes(b'approved image')
    item = {
        'artifact_id': 'artifact-1', 'target_module': 'RCM',
        'hardware_revision': 'RMC-NANO-ATMEGA328P', 'version': '1.2.3',
        'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'installer': 'firmware', 'signature': base64.b64encode(b'ok').decode(),
    }
    item.update(overrides)
    return item, staging


def test_verified_artifact_requires_target_revision_hash_and_signature(tmp_path):
    artifact, staging = _artifact(tmp_path)
    private = Ed25519PrivateKey.generate()
    artifact['signature'] = base64.b64encode(private.sign(policy._signed_body(artifact))).decode()
    result = policy.verify_artifact(
        artifact, target_module='RCM', hardware_revision='RMC-NANO-ATMEGA328P',
        trusted_public_key=private.public_key().public_bytes_raw(), staging_root=staging,
    )
    assert result.artifact_id == 'artifact-1'

    for field, value in [('target_module', 'LCM'), ('hardware_revision', 'other'), ('sha256', 'bad'), ('signature', '')]:
        bad = dict(artifact, **{field: value})
        with pytest.raises(policy.ArtifactError):
            policy.verify_artifact(
                bad, target_module='RCM', hardware_revision='RMC-NANO-ATMEGA328P',
                trusted_public_key=private.public_key().public_bytes_raw(), staging_root=staging,
            )


def test_artifact_rejects_traversal_and_symlink(tmp_path):
    artifact, staging = _artifact(tmp_path)
    private = Ed25519PrivateKey.generate()
    artifact['signature'] = base64.b64encode(private.sign(policy._signed_body(artifact))).decode()
    artifact['path'] = str(tmp_path / 'outside')
    (tmp_path / 'outside').write_bytes(b'outside')
    artifact['signature'] = base64.b64encode(private.sign(policy._signed_body(artifact))).decode()
    with pytest.raises(policy.ArtifactError, match='outside'):
        policy.verify_artifact(artifact, target_module='RCM', hardware_revision='RMC-NANO-ATMEGA328P', trusted_public_key=private.public_key().public_bytes_raw(), staging_root=staging)


def test_update_service_rejects_arbitrary_command_payload():
    assert service.artifact_policy.INSTALLERS[('RCM', 'firmware')]


@pytest.mark.asyncio
async def test_update_handler_rejects_command_without_spawning(monkeypatch):
    calls = []

    async def fail_spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError('subprocess must not be called')

    class Reader:
        pass

    class Writer:
        async def wait_closed(self):
            return None

        def close(self):
            return None

    async def read_frame(_reader):
        return {'type': 'update_run', 'payload': {'command': ['touch', '/tmp/should-not-run']}}

    sent = []
    async def write_frame(_writer, message):
        sent.append(message)

    monkeypatch.setattr(service.protocol, 'read_frame', read_frame)
    monkeypatch.setattr(service.protocol, 'write_frame', write_frame)
    monkeypatch.setattr(service.asyncio, 'create_subprocess_exec', fail_spawn)
    await service.UpdateService(allow_execute=True, request_secret=b'secret').handle(Reader(), Writer())
    assert calls == []
    assert sent[0]['payload']['ok'] is False


def test_update_request_authentication_and_replay_protection():
    clock = lambda: 1000.0
    updater = service.UpdateService(allow_execute=True, request_secret=b'secret', clock=clock)
    payload = {'artifact': {'artifact_id': 'artifact-1'}}
    request = {'type': 'update_run', 'payload': payload, 'request_id': 'request-1'}
    auth_fields = {'operation_id': 'operation-1', 'artifact_id': 'artifact-1', 'timestamp': 1000.0}
    canonical = json.dumps({**request, **auth_fields}, sort_keys=True, separators=(',', ':')).encode()
    request['auth'] = {**auth_fields, 'mac': __import__('hmac').new(b'secret', canonical, __import__('hashlib').sha256).hexdigest()}
    assert updater._authenticate_update_request(request, payload)[0] == 'operation-1'
    updater._accepted_operations['operation-1'] = 1000.0
    with pytest.raises(ValueError, match='duplicate'):
        updater._authenticate_update_request(request, payload)


def test_update_runtime_configuration_fails_closed_and_accepts_raw_key(tmp_path, monkeypatch):
    monkeypatch.setenv('HCM_UPDATE_EXECUTION_ENABLED', 'true')
    monkeypatch.delenv('HCM_UPDATE_TARGET_MODULE', raising=False)
    with pytest.raises(RuntimeError):
        service.UpdateService.from_environment()

    key = tmp_path / 'ed25519.pub'
    key.write_bytes(b'k' * 32)
    secret = tmp_path / 'request.secret'
    secret.write_bytes(b'request-secret')
    monkeypatch.setenv('HCM_UPDATE_TARGET_MODULE', 'LCM')
    monkeypatch.setenv('HCM_UPDATE_HARDWARE_REVISION', 'LCM-REV-A')
    monkeypatch.setenv('HCM_UPDATE_PUBLIC_KEY_FILE', str(key))
    monkeypatch.setenv('HCM_UPDATE_REQUEST_SECRET_FILE', str(secret))
    configured = service.UpdateService.from_environment()
    assert configured.target_module == 'LCM'
    assert configured.trusted_public_key == b'k' * 32


def test_update_runtime_configuration_disabled_may_start_without_key(monkeypatch):
    monkeypatch.setenv('HCM_UPDATE_EXECUTION_ENABLED', 'false')
    for name in ('HCM_UPDATE_TARGET_MODULE', 'HCM_UPDATE_HARDWARE_REVISION', 'HCM_UPDATE_PUBLIC_KEY_FILE', 'HCM_UPDATE_REQUEST_SECRET_FILE'):
        monkeypatch.delenv(name, raising=False)
    configured = service.UpdateService.from_environment()
    assert configured.allow_execute is False


def test_update_replay_store_survives_service_restart(tmp_path):
    first = service.UpdateService(request_secret=b'secret', clock=lambda: 1000.0, replay_store_path=tmp_path / 'replay.sqlite3')
    first._record_operation('operation-1', 'artifact-1')
    second = service.UpdateService(request_secret=b'secret', clock=lambda: 1001.0, replay_store_path=tmp_path / 'replay.sqlite3')
    request = {'type': 'update_run', 'payload': {'artifact': {'artifact_id': 'artifact-1'}}, 'request_id': 'request-1'}
    fields = {'operation_id': 'operation-1', 'artifact_id': 'artifact-1', 'timestamp': 1001.0}
    canonical = json.dumps({**request, **fields}, sort_keys=True, separators=(',', ':')).encode()
    request['auth'] = {**fields, 'mac': __import__('hmac').new(b'secret', canonical, __import__('hashlib').sha256).hexdigest()}

    with pytest.raises(ValueError, match='duplicate'):
        second._authenticate_update_request(request, request['payload'])
