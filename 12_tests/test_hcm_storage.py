from importlib import import_module
import asyncio
import subprocess

import pytest


storage = import_module('01_HCM.storage')


def test_storage_layout_initializes_local_git_and_expected_directories(tmp_path):
    result = storage.ensure_storage_layout(tmp_path)

    assert (tmp_path / 'config' / 'RCM').is_dir()
    assert (tmp_path / 'config' / 'LCM').is_dir()
    assert (tmp_path / 'config' / 'SIM').is_dir()
    assert (tmp_path / 'config' / 'system').is_dir()
    assert (tmp_path / 'logs' / 'HCM').is_dir()
    assert (tmp_path / '.git').is_dir()
    assert result['git_initialized'] is True


def test_git_settings_redact_pat_and_store_secret_outside_config(tmp_path):
    result = storage.update_git_settings(
        {
            'commit_name': 'HomeControl Admin',
            'commit_email': 'admin@example.test',
            'repo_url': 'https://github.com/example/private-homecontrol.git',
            'github_pat': 'ghp_secret',
            'github_enabled': True,
        },
        root=tmp_path,
    )

    assert result['commit_name'] == 'HomeControl Admin'
    assert result['repo_url'].endswith('private-homecontrol.git')
    assert result['github_token_configured'] is True
    assert 'ghp_secret' not in str(result)
    assert (tmp_path / '.secrets' / 'github_pat').read_text() == 'ghp_secret'
    assert 'ghp_secret' not in (tmp_path / 'config' / 'system' / 'git.json').read_text()

    disconnected = storage.disconnect_github(root=tmp_path)
    assert disconnected['github_enabled'] is False
    assert disconnected['github_token_configured'] is False


def test_git_settings_reject_embedded_url_credentials(tmp_path):
    with pytest.raises(ValueError):
        storage.update_git_settings({'repo_url': 'https://token@example.com/owner/repo.git'}, root=tmp_path)


def test_git_sync_commits_only_tracked_paths_and_skips_no_change(tmp_path):
    storage.ensure_storage_layout(tmp_path)
    storage.update_git_settings({'commit_name': 'Tester', 'commit_email': 'tester@example.test'}, root=tmp_path)
    (tmp_path / 'config' / 'system' / 'sample.json').write_text('{"ok": true}\n')
    (tmp_path / '.secrets').mkdir(exist_ok=True)
    (tmp_path / '.secrets' / 'do-not-track').write_text('secret')

    manager = storage.GitSyncManager(tmp_path, interval_s=600)
    first = manager._sync_once_blocking()
    second = manager._sync_once_blocking()
    tracked = subprocess.run(['git', 'ls-files'], cwd=tmp_path, text=True, capture_output=True, check=False)

    assert first['ok'] is True
    assert first['committed'] is True
    assert second['ok'] is True
    assert second['committed'] is False
    assert 'config/system/sample.json' in tracked.stdout
    assert '.secrets/do-not-track' not in tracked.stdout


def test_git_sync_uses_safe_default_identity_for_local_only_storage(tmp_path):
    storage.ensure_storage_layout(tmp_path)
    (tmp_path / 'config' / 'system' / 'default-identity.json').write_text('{}')

    result = storage.GitSyncManager(tmp_path)._sync_once_blocking()
    identity = subprocess.run(
        ['git', 'log', '-1', '--format=%an <%ae>'],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result['ok'] is True
    assert result['committed'] is True
    assert identity.stdout.strip() == 'HomeControl HCM <hcm@localhost>'


def test_repository_status_local_only_and_dirty(tmp_path):
    storage.ensure_storage_layout(tmp_path)
    status = storage.repository_status(tmp_path)
    assert status['display'] == 'Git Repository: Local Only'

    (tmp_path / 'config' / 'system' / 'dirty.json').write_text('{}')
    dirty = storage.repository_status(tmp_path)
    assert dirty['display'] == 'Git Repository: Local Only'
    assert dirty['dirty'] is True


def test_git_sync_retries_after_remote_outage_and_survives_recreated_manager(tmp_path):
    remote = tmp_path / 'remote.git'
    root = tmp_path / 'hcm-storage'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=False, capture_output=True, text=True)
    storage.ensure_storage_layout(root)
    storage.update_git_settings(
        {
            'commit_name': 'Tester',
            'commit_email': 'tester@example.test',
            'github_enabled': True,
        },
        root=root,
    )
    subprocess.run(['git', 'remote', 'add', 'origin', str(remote)], cwd=root, check=False, capture_output=True, text=True)
    (root / 'config' / 'system' / 'first.json').write_text('{"first": true}\n')

    manager = storage.GitSyncManager(root)
    first = manager._sync_once_blocking()
    subprocess.run(['git', 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git')], cwd=root, check=False, capture_output=True, text=True)
    (root / 'config' / 'system' / 'second.json').write_text('{"second": true}\n')
    failed = storage.GitSyncManager(root)._sync_once_blocking()
    subprocess.run(['git', 'remote', 'set-url', 'origin', str(remote)], cwd=root, check=False, capture_output=True, text=True)
    retried = storage.GitSyncManager(root)._sync_once_blocking()
    remote_head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=remote, text=True, capture_output=True, check=False)

    assert first['ok'] is True
    assert first['pushed'] is True
    assert failed['ok'] is False
    assert failed['error'] == 'push_failed'
    assert retried['ok'] is True
    assert retried['pushed'] is True
    assert remote_head.returncode == 0


@pytest.mark.asyncio
async def test_git_sync_manager_lock_prevents_overlapping_jobs(tmp_path):
    storage.ensure_storage_layout(tmp_path)
    storage.update_git_settings({'commit_name': 'Tester', 'commit_email': 'tester@example.test'}, root=tmp_path)
    (tmp_path / 'config' / 'system' / 'a.json').write_text('{}')
    manager = storage.GitSyncManager(tmp_path, interval_s=600)

    results = await asyncio.gather(manager.sync_once(), manager.sync_once())

    assert all(result['ok'] for result in results)
    assert sum(1 for result in results if result['committed']) == 1


@pytest.mark.asyncio
async def test_connect_github_validates_private_write_repo_and_redacts_pat(tmp_path, monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {'private': True, 'permissions': {'push': True}}

    class FakeClient:
        async def get(self, url, headers):
            assert headers['Authorization'] == 'Bearer ghp_secret'
            return FakeResponse()

    storage.ensure_storage_layout(tmp_path)
    subprocess.run(['git', 'commit', '--allow-empty', '-m', 'initial'], cwd=tmp_path, check=False, capture_output=True, text=True)
    real_run_git = storage._run_git
    def fake_run_git(root, args, **kwargs):
        if args[:1] == ['ls-remote']:
            return subprocess.CompletedProcess(['git', *args], 0, 'refs/heads/main\n', '')
        return real_run_git(root, args, **kwargs)
    monkeypatch.setattr(storage, '_run_git', fake_run_git)
    result = await storage.connect_github(
        {
            'commit_name': 'Tester',
            'commit_email': 'tester@example.test',
            'repo_url': 'https://github.com/example/private.git',
            'github_pat': 'ghp_secret',
        },
        root=tmp_path,
        client=FakeClient(),
    )

    assert result['github_enabled'] is True
    assert result['github_token_configured'] is True
    assert 'ghp_secret' not in str(result)
