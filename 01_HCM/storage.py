from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from importlib import import_module

from .settings import settings

infra = import_module('07_servises.common.module_infra')


CONFIG_DIRS = ('RCM', 'LCM', 'SIM', 'system')
LOG_DIRS = ('HCM',)
TRACKED_PATHS = ('config', 'logs', 'recovery-manifest.json')
SYNC_INTERVAL_SECONDS = 600


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
    if git_initialized:
        _ensure_gitignore(root)
    return {
        'root': str(root),
        'config_dirs': [str(root / 'config' / name) for name in CONFIG_DIRS],
        'log_dirs': [str(root / 'logs' / name) for name in LOG_DIRS],
        'git_initialized': git_initialized,
    }


def _ensure_gitignore(root: Path) -> None:
    gitignore = root / '.gitignore'
    desired = "\n".join([
        '*',
        '!config/',
        '!config/**',
        '!logs/',
        '!logs/**',
        '!recovery-manifest.json',
        '!.gitignore',
        '.secrets/',
        '*.key',
        '*.pem',
        '*.crt',
        '*.db',
        '*.sqlite',
        '*.tmp',
        '',
    ])
    if not gitignore.exists() or gitignore.read_text() != desired:
        infra.atomic_write_text(gitignore, desired)


def _run_git(root: Path, args: list[str], *, env: dict[str, str] | None = None, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **(env or {})},
        timeout=timeout,
    )


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


def _status_path(root: Path) -> Path:
    return root / '.state' / 'git-status.json'


def _save_git_status(root: Path, value: dict[str, Any]) -> None:
    infra.atomic_write_text(_status_path(root), json.dumps(value, indent=2, sort_keys=True))


def _load_git_status(root: Path) -> dict[str, Any]:
    return _load_json(_status_path(root))


def _ensure_git_identity(root: Path) -> None:
    """Ensure local-only snapshots can commit without requiring GitHub setup."""
    configured = _load_json(_git_config_path(root))
    defaults = {
        'user.name': str(configured.get('commit_name') or 'HomeControl HCM'),
        'user.email': str(configured.get('commit_email') or 'hcm@localhost'),
    }
    for key, value in defaults.items():
        current = _run_git(root, ['config', '--local', '--get', key])
        if current.returncode != 0 or not current.stdout.strip():
            _run_git(root, ['config', '--local', key, value])


def get_git_settings(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    ensure_storage_layout(root)
    data = _load_json(_git_config_path(root))
    remote_name = data.get('remote_name') if data.get('github_enabled') else None
    status = repository_status(root, remote_name=remote_name)
    saved_status = _load_git_status(root)
    if saved_status.get('last_error') and status['display'] != 'Git Repository: Up to Date':
        status['reason'] = saved_status['last_error']
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
    if repo_url and parsed and parsed.scheme not in {'https', 'ssh', 'git'}:
        raise ValueError('Repository URL scheme is not allowed')
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


async def connect_github(body: dict[str, Any], root: Path | None = None, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    repo_url = str(body.get('repo_url', '')).strip()
    token = str(body.get('github_pat', '')).strip()
    owner_repo = _github_owner_repo(repo_url)
    if not owner_repo:
        raise ValueError('GitHub repository URL is invalid')
    if not token:
        raise ValueError('GitHub personal access token is required')
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.get(
            f'https://api.github.com/repos/{owner_repo}',
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'},
        )
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code == 404:
        raise ValueError('GitHub repository was not found or credentials do not grant access')
    if response.status_code in {401, 403}:
        raise ValueError('GitHub credentials were rejected')
    if response.status_code >= 400:
        raise ValueError('GitHub repository verification failed')
    data = response.json()
    if data.get('private') is not True:
        raise ValueError('GitHub repository must be private')
    permissions = data.get('permissions') or {}
    if permissions.get('push') is not True and permissions.get('admin') is not True and permissions.get('maintain') is not True:
        raise ValueError('GitHub credentials do not provide write access')
    updated = update_git_settings({**body, 'github_enabled': True}, root=root)
    remote = _run_git(root, ['ls-remote', '--heads', updated['remote_name']], env=_git_auth_env(root), timeout=30.0)
    if remote.returncode != 0:
        _save_git_status(root, {'last_error': 'GitHub remote history could not be verified'})
        raise ValueError('GitHub remote history could not be verified')
    _save_git_status(root, {'last_error': None, 'last_verified_at': infra.utc_ts()})
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


def _github_owner_repo(repo_url: str) -> str | None:
    parsed = urlsplit(repo_url)
    if parsed.username or parsed.password:
        raise ValueError('Repository URL must not contain embedded credentials')
    if parsed.netloc.lower() == 'github.com':
        path = parsed.path.strip('/').removesuffix('.git')
        parts = path.split('/')
        if len(parts) == 2 and all(parts):
            return f'{parts[0]}/{parts[1]}'
    if repo_url.startswith('git@github.com:'):
        path = repo_url.split(':', 1)[1].strip().removesuffix('.git')
        parts = path.split('/')
        if len(parts) == 2 and all(parts):
            return f'{parts[0]}/{parts[1]}'
    return None


def _git_auth_env(root: Path) -> dict[str, str]:
    token_file = _token_path(root)
    if not token_file.exists():
        return {'GIT_TERMINAL_PROMPT': '0'}
    askpass = root / '.secrets' / 'git-askpass.sh'
    script = '#!/bin/sh\ncase "$1" in\n*Username*) printf "%s" "x-access-token" ;;\n*Password*) cat "$(dirname "$0")/github_pat" ;;\n*) printf "" ;;\nesac\n'
    if not askpass.exists() or askpass.read_text() != script:
        infra.atomic_write_text(askpass, script, mode=0o700)
    return {
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_ASKPASS': str(askpass),
    }


def repository_status(root: Path | None = None, remote_name: str | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    if not (root / '.git').exists():
        return {'local_enabled': False, 'remote_configured': False, 'display': 'Git Repository: Not Synced', 'reason': 'Local Git repository is not initialized'}
    status = _run_git(root, ['status', '--porcelain', '--', *TRACKED_PATHS])
    dirty = status.returncode != 0 or bool(status.stdout.strip())
    remote_configured = bool(remote_name)
    unpushed = False
    diverged = False
    if remote_configured:
        branch = _run_git(root, ['rev-parse', '--abbrev-ref', 'HEAD'])
        if branch.returncode == 0:
            local_branch = branch.stdout.strip()
            upstream = f'{remote_name}/{local_branch}'
            left_right = _run_git(root, ['rev-list', '--left-right', '--count', f'HEAD...{upstream}'])
            if left_right.returncode == 0:
                left, right = [int(part) for part in left_right.stdout.split()[:2]]
                unpushed = left > 0
                diverged = left > 0 and right > 0
            else:
                unpushed = True
    if not remote_configured:
        display = 'Git Repository: Local Only'
    elif dirty or unpushed or diverged:
        display = 'Git Repository: Not Synced'
    else:
        display = 'Git Repository: Up to Date'
    reason = None
    if diverged:
        reason = 'Local and remote histories diverged'
    elif dirty:
        reason = 'Tracked local changes are pending'
    elif unpushed:
        reason = 'Local commits are pending upload'
    return {
        'local_enabled': True,
        'remote_configured': remote_configured,
        'dirty': dirty,
        'unpushed': unpushed,
        'diverged': diverged,
        'display': display,
        'reason': reason,
    }


def update_recovery_manifest(root: Path | None = None, *, release: str | None = None, logical_modules: list[str] | None = None) -> dict[str, Any]:
    root = Path(root or storage_root())
    ensure_storage_layout(root)
    logs: dict[str, str | None] = {}
    for path in (root / 'logs').glob('**/*'):
        if path.is_file():
            logs[str(path.relative_to(root))] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(path.stat().st_mtime))
    manifest_core = {
        'hcm_software_release': release or os.getenv('HCM_RELEASE_SHA') or 'unknown',
        'configuration_schema_version': 1,
        'logical_module_identifiers': sorted(logical_modules or []),
        'latest_archived_log_timestamps': logs,
    }
    path = root / 'recovery-manifest.json'
    existing = _load_json(path)
    existing_core = {key: value for key, value in existing.items() if key != 'snapshot_timestamp'}
    manifest = {**manifest_core, 'snapshot_timestamp': existing.get('snapshot_timestamp') if existing_core == manifest_core else infra.utc_ts()}
    if existing != manifest:
        infra.atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


class GitSyncManager:
    def __init__(self, root: Path | None = None, *, interval_s: int = SYNC_INTERVAL_SECONDS):
        self.root = Path(root or storage_root())
        self.interval_s = int(interval_s)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.running = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.running = True
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while self.running:
            await self.sync_once()
            await asyncio.sleep(self.interval_s)

    async def sync_once(self) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._sync_once_blocking)

    def _sync_once_blocking(self) -> dict[str, Any]:
        ensure_storage_layout(self.root)
        _ensure_git_identity(self.root)
        update_recovery_manifest(self.root)
        status_before = repository_status(self.root)
        if status_before.get('diverged'):
            _save_git_status(self.root, {'last_error': 'Local and remote histories diverged', 'last_sync_at': infra.utc_ts()})
            return {'ok': False, 'pushed': False, 'committed': False, 'error': 'remote_diverged'}
        _run_git(self.root, ['add', '--', *TRACKED_PATHS])
        diff = _run_git(self.root, ['diff', '--cached', '--quiet', '--', *TRACKED_PATHS])
        committed = False
        if diff.returncode == 1:
            message = f'HomeControl configuration snapshot {infra.utc_ts()}'
            commit = _run_git(self.root, ['commit', '-m', message])
            if commit.returncode != 0:
                _save_git_status(self.root, {'last_error': 'Local Git commit failed', 'last_sync_at': infra.utc_ts()})
                return {'ok': False, 'pushed': False, 'committed': False, 'error': 'commit_failed'}
            committed = True
        elif diff.returncode not in {0, 1}:
            _save_git_status(self.root, {'last_error': 'Local Git change detection failed', 'last_sync_at': infra.utc_ts()})
            return {'ok': False, 'pushed': False, 'committed': False, 'error': 'diff_failed'}
        settings_data = _load_json(_git_config_path(self.root))
        remote_name = settings_data.get('remote_name', 'origin') if settings_data.get('github_enabled') else None
        pushed = False
        if remote_name:
            status = repository_status(self.root, remote_name=remote_name)
            if status.get('diverged'):
                _save_git_status(self.root, {'last_error': 'Local and remote histories diverged', 'last_sync_at': infra.utc_ts()})
                return {'ok': False, 'pushed': False, 'committed': committed, 'error': 'remote_diverged'}
            push = _run_git(self.root, ['push', remote_name, 'HEAD'], env=_git_auth_env(self.root), timeout=60.0)
            if push.returncode != 0:
                _save_git_status(self.root, {'last_error': 'GitHub push failed; will retry', 'last_sync_at': infra.utc_ts()})
                return {'ok': False, 'pushed': False, 'committed': committed, 'error': 'push_failed'}
            pushed = True
        _save_git_status(self.root, {'last_error': None, 'last_sync_at': infra.utc_ts()})
        return {'ok': True, 'pushed': pushed, 'committed': committed}


git_sync_manager = GitSyncManager()
