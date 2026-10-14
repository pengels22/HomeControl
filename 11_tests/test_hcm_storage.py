from importlib import import_module

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
