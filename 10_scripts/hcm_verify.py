#!/usr/bin/env python3
"""Read-only image/runtime verification. Never starts app lifespan or accesses GPIO."""
import argparse
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def verify_runtime(base_url, expected_sha):
    def get(path, status=200):
        try:
            response = urlopen(base_url.rstrip('/') + path, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            if response.code != status:
                raise RuntimeError('{} returned {}, expected {}'.format(path, response.code, status))
            return response.read()
    identity = json.loads(get('/api/v1/version'))
    if identity.get('git_sha') != expected_sha:
        raise RuntimeError('runtime SHA does not match expected release')
    if json.loads(get('/api/v1/health')).get('ok') is not True:
        raise RuntimeError('health check failed')
    get('/api/v1/safety/status', 401)
    if b'api("/safety/status")' not in get('/static/app.js'):
        raise RuntimeError('dashboard safety-status code missing')
    # Probe a random nonexistent identity; never use a real user's credentials.
    import secrets
    request = Request(base_url.rstrip('/') + '/api/v1/auth/login',
                      data=json.dumps({'username': 'probe_' + secrets.token_hex(12),
                                       'password': secrets.token_hex(24)}).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        if response.code != 401 or not isinstance(json.loads(response.read()), dict):
            raise RuntimeError('login acceptance failed: expected JSON 401 for nonexistent user')
    return identity


def verify_image(expected_sha):
    import os
    from importlib import import_module
    from pathlib import Path
    # Override any environment before importing main; no lifespan is entered.
    os.environ['HCM_SAFETY_INPUT_BACKEND'] = 'simulated'
    main = import_module('01_HCM.main')
    if 'get' not in main.app.openapi()['paths'].get('/api/v1/safety/status', {}):
        raise RuntimeError('safety route missing from actual app')
    root = Path(main.__file__).parent
    if "@router.get('/safety/status')" not in (root / 'api.py').read_text():
        raise RuntimeError('safety route source missing')
    if 'api("/safety/status")' not in (root / 'www/app.js').read_text():
        raise RuntimeError('dashboard safety-status code missing')
    identity = import_module('01_HCM.build_info').build_info()
    if identity['git_sha'] != expected_sha:
        raise RuntimeError('image SHA mismatch')
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--url')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.expected_sha):
        parser.error('expected SHA must be a full Git commit SHA')
    print(json.dumps(verify_runtime(args.url, args.expected_sha) if args.url else verify_image(args.expected_sha)))


if __name__ == '__main__':
    main()
