from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from importlib import import_module

from .settings import settings

infra = import_module('07_servises.common.module_infra')


CONFIG_DIRS = ('RCM', 'LCM', 'SIM', 'system')
LOG_DIRS = ('HCM',)


def storage_root() -> Path:
    return Path(settings.storage_root)


def ensure_storage_layout(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    for name in CONFIG_DIRS:
        (root / 'config' / name).mkdir(parents=True, exist_ok=True)
    for name in LOG_DIRS:
        (root / 'logs' / name).mkdir(parents=True, exist_ok=True)
    git_dir = root / '.git'
    git_initialized = git_dir.exists()
    if not git_initialized:
        result = subprocess.run(['git', 'init'], cwd=root, capture_output=True, text=True, check=False)
        git_initialized = result.returncode == 0
    return {
        'root': str(root),
        'config_dirs': [str(root / 'config' / name) for name in CONFIG_DIRS],
        'log_dirs': [str(root / 'logs' / name) for name in LOG_DIRS],
        'git_initialized': git_initialized,
    }


def _git_config_path(root: Path) -> Path:
    return root / 'config' / 'system' / 'git.json'


def _token_path(root: Path) -> Path:
    return root / '.secrets' / 'github_pat'


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def get_git_settings(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    ensure_storage_layout(root)
    data = _load_json(_git_config_path(root))
    remote_name = data.get('remote_name') if data.get('github_enabled') else None
    status = infra.git_status_simple(root, remote_name=remote_name)
    token_configured = _token_path(root).exists()
    return {
        'storage_root': str(root),
        'commit_name': data.get('commit_name', ''),
        'commit_email': data.get('commit_email', ''),
        'repo_url': data.get('repo_url', ''),
        'remote_name': data.get('remote_name', 'origin'),
        'github_enabled': bool(data.get('github_enabled')),
        'github_token_configured': token_configured,
        'status': status,
    }


def update_git_settings(body: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    ensure_storage_layout(root)
    current = _load_json(_git_config_path(root))
    repo_url = str(body.get('repo_url', current.get('repo_url', ''))).strip()
    parsed = urlsplit(repo_url) if repo_url else None
    if parsed and (parsed.username or parsed.password):
        raise ValueError('Repository URL must not contain embedded credentials')
    next_data = {
        **current,
        'commit_name': str(body.get('commit_name', current.get('commit_name', ''))).strip(),
        'commit_email': str(body.get('commit_email', current.get('commit_email', ''))).strip(),
        'repo_url': repo_url,
        'remote_name': str(body.get('remote_name', current.get('remote_name', 'origin')) or 'origin').strip(),
        'github_enabled': bool(body.get('github_enabled', current.get('github_enabled', False))),
    }
    infra.atomic_write_text(_git_config_path(root), json.dumps(next_data, indent=2, sort_keys=True))
    if next_data['commit_name']:
        subprocess.run(['git', 'config', 'user.name', next_data['commit_name']], cwd=root, check=False, capture_output=True, text=True)
    if next_data['commit_email']:
        subprocess.run(['git', 'config', 'user.email', next_data['commit_email']], cwd=root, check=False, capture_output=True, text=True)
    if next_data['repo_url']:
        existing = subprocess.run(['git', 'remote', 'get-url', next_data['remote_name']], cwd=root, check=False, capture_output=True, text=True)
        cmd = ['git', 'remote', 'set-url' if existing.returncode == 0 else 'add', next_data['remote_name'], next_data['repo_url']]
        subprocess.run(cmd, cwd=root, check=False, capture_output=True, text=True)
    token = body.get('github_pat')
    if token:
        secret = _token_path(root)
        secret.parent.mkdir(parents=True, exist_ok=True)
        infra.atomic_write_text(secret, str(token).strip(), mode=0o600)
    return get_git_settings(root)


def disconnect_github(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    data = _load_json(_git_config_path(root))
    data['github_enabled'] = False
    infra.atomic_write_text(_git_config_path(root), json.dumps(data, indent=2, sort_keys=True))
    try:
        os.remove(_token_path(root))
    except FileNotFoundError:
        pass
    return get_git_settings(root)
