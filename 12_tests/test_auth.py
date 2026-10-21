from importlib import import_module

import pytest
from fastapi import HTTPException

auth = import_module('01_HCM.auth')


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAuthConn:
    def __init__(self):
        self.users = {}
        self.sessions = []
        self.login_limits = {}
        self.pairing = {}
        self.next_pairing_id = 1

    async def execute(self, query, *args):
        if 'INSERT INTO users' in query:
            username, role, password_hash = args
            self.users[username] = {'username': username, 'role': role, 'password_hash': password_hash}
            return
        if 'INSERT INTO user_sessions' in query:
            self.sessions.append(args)
            return
        if 'auth_login_rate_limits' in query:
            if query.startswith('DELETE'):
                self.login_limits.pop(args[0], None)
            else:
                self.login_limits[args[0]] = {'failed_attempts': args[1], 'next_allowed_at': object() if args[1] >= 5 else None}
            return
        raise AssertionError(f'unexpected execute: {query}')

    async def fetchrow(self, query, *args):
        if 'auth_login_rate_limits' in query:
            row = self.login_limits.get(args[0])
            if 'next_allowed_at > now()' in query:
                return row if row and row.get('next_allowed_at') is not None else None
            if 'FOR UPDATE' in query:
                return row
            return row
        if 'FROM users WHERE username=$1' in query:
            return self.users.get(args[0])
        if 'INSERT INTO pairing_keys' in query:
            label, target_type, token_hash, created_by, ttl_minutes, metadata = args
            row = {
                'id': self.next_pairing_id,
                'label': label,
                'target_type': target_type,
                'expires_at': FakeDateTime(),
                'token_hash': token_hash,
                'used': False,
                'metadata': metadata,
            }
            self.next_pairing_id += 1
            self.pairing[token_hash] = row
            return row
        if 'UPDATE pairing_keys' in query:
            token_hash, used_by = args
            row = self.pairing.get(token_hash)
            if not row or row['used']:
                return None
            row['used'] = True
            row['used_by'] = used_by
            return {
                'id': row['id'],
                'label': row['label'],
                'target_type': row['target_type'],
                'metadata': row['metadata'],
            }
        raise AssertionError(f'unexpected fetchrow: {query}')


class FakeDateTime:
    def isoformat(self):
        return '2026-10-01T12:00:00'


class FakeSessionConn:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, query, *args):
        return self.row


class FakePasswordConn:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def fetchrow(self, query, *args):
        if 'UPDATE users' in query and 'SET password_hash' in query:
            return {'username': 'patrick', 'role': 'ADMIN', 'enabled': True, 'created_at': FakeDateTime()}
        if query.startswith('SELECT username, password_hash'):
            return {'username': 'patrick', 'password_hash': auth.hash_password('old password long')}
        raise AssertionError(query)


@pytest.mark.asyncio
async def test_persistent_session_uses_current_enabled_role(monkeypatch):
    conn = FakeSessionConn({'username': 'patrick', 'role': 'READONLY'})
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(auth, '_token_hash', lambda token: 'hash')
    result = await auth.require_user('Bearer token')
    assert result == {'user': 'patrick', 'role': 'READONLY'}


@pytest.mark.asyncio
async def test_password_reset_and_change_clear_login_rate_state(monkeypatch):
    conn = FakePasswordConn()
    cleared = []
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))
    async def clear(_conn, username):
        cleared.append(username)
    monkeypatch.setattr(auth, '_clear_normal_login_rate', clear)

    await auth.reset_user_password('patrick', 'new password long')
    await auth.change_own_password('patrick', 'old password long', 'newer password long')
    assert cleared == ['patrick', 'patrick']


def test_password_hash_does_not_store_plain_text_and_verifies():
    password_hash = auth.hash_password('correct horse battery staple')

    assert 'correct horse battery staple' not in password_hash
    assert auth.verify_password('correct horse battery staple', password_hash)
    assert not auth.verify_password('wrong password', password_hash)


def test_touchscreen_pin_uses_scrypt_and_hmac_lookup_without_plaintext(monkeypatch, tmp_path):
    secret = tmp_path / 'pin-secret'
    secret.write_bytes(b'x' * 32)
    monkeypatch.setattr(auth.settings, 'touchscreen_pin_lookup_secret_file', secret)
    verifier = auth.hash_touchscreen_pin('123456')
    lookup = auth.touchscreen_pin_lookup('123456')
    assert verifier.startswith('scrypt$')
    assert auth.verify_touchscreen_pin('123456', verifier)
    assert not auth.verify_touchscreen_pin('123455', verifier)
    assert '123456' not in verifier and '123456' not in lookup


def test_in_memory_session_uses_configured_default_ttl(monkeypatch):
    monkeypatch.setattr(auth.settings, 'auth_session_ttl_s', 7)
    monkeypatch.setattr(auth.time, 'time', lambda: 100.0)

    token = auth.create_session('patrick', 'ADMIN')

    assert auth._sessions[token] == ('patrick', 'ADMIN', 107.0)


@pytest.mark.asyncio
async def test_password_login_creates_persistent_session(monkeypatch):
    conn = FakeAuthConn()
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))
    await auth.create_user('patrick', 'correct horse battery staple', 'ADMIN')

    token = await auth.login_password('patrick', 'correct horse battery staple')

    assert token
    assert len(conn.sessions) == 1


@pytest.mark.asyncio
async def test_password_login_rejects_bad_password(monkeypatch):
    conn = FakeAuthConn()
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))
    await auth.create_user('patrick', 'correct horse battery staple', 'ADMIN')

    with pytest.raises(HTTPException) as exc:
        await auth.login_password('patrick', 'wrong password')

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_password_login_locks_after_five_failures_and_clears_on_success(monkeypatch):
    conn = FakeAuthConn()
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))
    await auth.create_user('patrick', 'correct horse battery staple', 'ADMIN')

    for _ in range(5):
        with pytest.raises(HTTPException) as exc:
            await auth.login_password('patrick', 'wrong password')
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        await auth.login_password('patrick', 'correct horse battery staple')
    assert exc.value.status_code == 429

    conn.login_limits['patrick']['next_allowed_at'] = None
    token = await auth.login_password('patrick', 'correct horse battery staple')
    assert token and 'patrick' not in conn.login_limits


@pytest.mark.asyncio
async def test_malformed_login_username_is_rejected_before_rate_limit_storage(monkeypatch):
    async def unexpected_acquire():
        raise AssertionError('malformed username must not access the database')

    monkeypatch.setattr(auth.db, 'acquire', unexpected_acquire)
    with pytest.raises(HTTPException) as exc:
        await auth.login_password('bad username!', 'irrelevant')
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_pairing_key_is_returned_once_but_only_hash_is_stored(monkeypatch):
    conn = FakeAuthConn()
    monkeypatch.setattr(auth.db, 'acquire', lambda: FakeAcquire(conn))

    created = await auth.create_pairing_key('Kitchen panel', 'PNL', 'patrick', 30)
    stored_hashes = list(conn.pairing.keys())

    assert created['pairing_key']
    assert created['pairing_key'] not in stored_hashes
    verified = await auth.verify_pairing_key(created['pairing_key'], 'PNL01')
    assert verified['ok'] is True

    with pytest.raises(HTTPException) as exc:
        await auth.verify_pairing_key(created['pairing_key'], 'PNL01')

    assert exc.value.status_code == 401
