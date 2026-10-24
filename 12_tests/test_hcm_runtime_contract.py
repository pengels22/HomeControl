"""Exercise the real application without lifespan, database, network peers or GPIO."""
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def main(monkeypatch):
    settings = import_module('02_HCM.settings').settings
    monkeypatch.setattr(settings, 'safety_input_backend', 'simulated')
    return import_module('02_HCM.main')


@pytest.fixture
def client(main):
    # Deliberately no context manager: do not run the production lifespan.
    return TestClient(main.app)


def test_actual_app_route_and_authentication(main, client):
    assert 'get' in main.app.openapi()['paths']['/api/v1/safety/status']
    assert client.get('/api/v1/safety/status').status_code == 401


@pytest.mark.parametrize('status', ['Normal', 'Active', 'Unknown'])
def test_authenticated_status_with_all_modules_offline(main, client, monkeypatch, status):
    auth = import_module('02_HCM.auth')
    monkeypatch.setattr(auth.settings, 'dev_mode', True)
    token = auth.create_session('reader', 'READONLY')
    safety = import_module('02_HCM.safety')
    controller = safety.SafetyController(None, safety_relays=SimpleNamespace(
        backend=SimpleNamespace(physical_input_authoritative=True)))
    monkeypatch.setattr(safety.time, 'time', lambda: 100.0)
    controller.last_input_sample_wall = 100.0
    controller.fire_input_fault = status == 'Unknown'
    controller.fire_active = status == 'Active'
    monkeypatch.setattr(main.api, 'safety', controller)
    class OfflineRegistry:
        def __getattr__(self, name):
            raise AssertionError('safety status must not consult field modules')
    monkeypatch.setattr(main.api, 'registry', OfflineRegistry())
    response = client.get('/api/v1/safety/status', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 200
    assert response.json() == {'ok': True, **controller.status_payload()}
    assert response.json()['status'] == status
    auth._sessions.pop(token)


def test_version_uses_embedded_file(main, client, monkeypatch, tmp_path):
    info = import_module('02_HCM.build_info')
    path = tmp_path / 'build_info.json'
    expected = {'version': '0.1.0', 'git_sha': 'a' * 40, 'build_time': '2026-10-19T00:00:00Z'}
    path.write_text(json.dumps(expected))
    monkeypatch.setattr(info, 'BUILD_INFO_PATH', path)
    monkeypatch.setenv('HCM_GIT_SHA', 'stale-container-environment')
    assert client.get('/api/v1/version').json() == expected


async def test_physical_init_failure_is_unknown_not_simulation(main, monkeypatch):
    relays = import_module('02_HCM.safety_relays')
    monkeypatch.setattr(main.settings, 'safety_input_backend', 'linux')
    def fail(*args, **kwargs):
        raise OSError('GPIO unavailable')
    monkeypatch.setattr(relays.physical_drivers, 'LinuxGPIOInputTransport', fail)
    backend = main.build_safety_relays()
    controller = main.SafetyController(None, safety_relays=backend, heartbeat=AsyncMock())
    await controller.sample_fire_input_from_backend(now=1)
    await controller.sample_ac_power_from_backend(now=1)
    payload = controller.status_payload()
    assert payload['status'] == 'Unknown'
    assert payload['physical_input_authoritative'] is True
    assert payload['fire_alarm_P']['state'] == 'unknown'
    with pytest.raises(PermissionError):
        await controller.set_fire(False)


async def test_linux_backend_read_failure_is_unknown(monkeypatch):
    relays = import_module('02_HCM.safety_relays')
    class BrokenTransport:
        def __init__(self, *args): pass
        def read(self): raise OSError('read failed')
        def close(self): pass
    monkeypatch.setattr(relays.physical_drivers, 'LinuxGPIOInputTransport', BrokenTransport)
    backend = relays.HCMSafetyRelayController.from_linux()
    controller = import_module('02_HCM.safety').SafetyController(None, safety_relays=backend, heartbeat=AsyncMock())
    await controller.sample_fire_input_from_backend(now=1)
    assert controller.status_payload()['status'] == 'Unknown'
    assert controller.physical_fire_input_authoritative()


def test_dashboard_safety_is_independent_and_preserves_unknown(client):
    js = client.get('/static/app.js').text
    assert 'api("/safety/status")' in js
    section = js[js.index('  const fireStatus ='):js.index('  const conflictReported')]
    assert 'safetyStatus?.status' in section
    assert 'module' not in section.lower()
    assert 'const fireReported = ["Normal", "Active", "Unknown"].includes(fireStatus);' in js


def test_build_path_embeds_sha_and_checks_image(tmp_path):
    (tmp_path / '02_HCM').mkdir()
    sha = 'b' * 40
    subprocess.run([sys.executable, str(ROOT / '11_scripts/hcm_build_info.py'), sha], cwd=tmp_path, check=True)
    assert json.loads((tmp_path / '02_HCM/build_info.json').read_text())['git_sha'] == sha
    dockerfile = (ROOT / '07_config/02_HCM/Dockerfile.live').read_text()
    assert 'ARG HCM_GIT_SHA' in dockerfile
    assert 'hcm_verify.py --expected-sha "$HCM_GIT_SHA"' in dockerfile
    adapters = (ROOT / '07_config/10_Common/adapters.py').read_text()
    assert '--build-arg HCM_GIT_SHA={artifact.release}' in adapters
    assert '--expected-sha {artifact.release}' in adapters


@pytest.mark.parametrize('bad', [None, 'sha', 'route', 'health', 'static', 'login'])
def test_runtime_verifier_rejects_old_or_incomplete_release(monkeypatch, bad):
    verify = import_module('11_scripts.hcm_verify')
    sha = 'c' * 40
    responses = {
        '/api/v1/auth/login': (500 if bad == 'login' else 401, b'{"detail":"invalid username/password"}'),
        '/api/v1/version': (200, json.dumps({'git_sha': 'old' if bad == 'sha' else sha}).encode()),
        '/api/v1/health': (200, json.dumps({'ok': bad != 'health'}).encode()),
        '/api/v1/safety/status': (404 if bad == 'route' else 401, b''),
        '/static/app.js': (200, b'old' if bad == 'static' else b'api("/safety/status")'),
    }
    class Response:
        def __init__(self, code, body): self.code, self.body = code, body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(verify, 'urlopen', lambda url, timeout: Response(*responses[(url if isinstance(url, str) else url.full_url).removeprefix('http://test')]))
    if bad:
        with pytest.raises(RuntimeError):
            verify.verify_runtime('http://test', sha)
    else:
        assert verify.verify_runtime('http://test', sha)['git_sha'] == sha
