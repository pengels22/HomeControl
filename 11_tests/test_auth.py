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
        raise AssertionError(f'unexpected execute: {query}')

    async def fetchrow(self, query, *args):
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


def test_password_hash_does_not_store_plain_text_and_verifies():
    password_hash = auth.hash_password('correct horse battery staple')

    assert 'correct horse battery staple' not in password_hash
    assert auth.verify_password('correct horse battery staple', password_hash)
    assert not auth.verify_password('wrong password', password_hash)


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
