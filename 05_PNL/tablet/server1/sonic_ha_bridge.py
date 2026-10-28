#!/usr/bin/env python3
"""Loopback-only Sonic bridge: authenticated WAV -> Whisper -> HA Assist."""
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from panel_api import PanelError, get_panel, panel_authorized, post_panel

TOKEN = os.environ.get('SONIC_API_TOKEN', '')
FIRE7_TOKEN = os.environ.get('SONIC_FIRE7_TOKEN', '')
HA_TOKEN_PATH = Path('/etc/sonic-ha/ha-token')
HA_URL = os.environ.get('SONIC_HA_URL', 'http://192.168.1.8:8123').rstrip('/')
MAX_BODY = 1100000
TODO_LISTS = {
    'costco': 'todo.costco',
    'cost co': 'todo.costco',
    'costo': 'todo.costco',
    'costoc': 'todo.costco',
    'meijer': 'todo.meijer',
    'meijers': 'todo.meijer',
    'meijor': 'todo.meijer',
    'meijors': 'todo.meijer',
    'myer': 'todo.meijer',
    'myers': 'todo.meijer',
    'home depot': 'todo.home_depot',
    'home depo': 'todo.home_depot',
    'homedepot': 'todo.home_depot',
    'homedepo': 'todo.home_depot',
}


def request(url, *, method='GET', headers=None, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        if res.status not in (200, 204):
            raise RuntimeError('unexpected_upstream_status')
        return res.read(262144)


def policy_allows():
    raw = request('http://127.0.0.1:8766/mic-policy', headers={'Authorization': 'Bearer ' + TOKEN}, timeout=3)
    state = json.loads(raw)
    return state.get('global_mute') is False and type(state.get('version')) is int


def grocery_command(transcript):
    """Return (item, todo entity) for an explicitly named shopping-list command."""
    text = transcript.strip()
    verb = re.search(r'\b(?:add|at|and|put|place)\b', text, re.IGNORECASE)
    if verb:
        text = text[verb.start():]
    prefix = r'(?:(?:hey\s+)?jarvis[,:]?\s+)?(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?'
    pattern = r'^' + prefix + r'(?:add|at|and|put|place)\s+(.+?)\s+(?:to|on|for)\s+(?:(?:my|the|our)\s+)?(cost\s*(?:co|o|oc)|meijors?|meijers?|myers?|home\s*depot|home\s*depo)(?:[\'’]s)?(?:\s+(?:(?:shopping|grocery)\s+)?list)?[.!?]*$'
    match = re.match(pattern, text, re.IGNORECASE)
    if not match:
        pattern = r'^' + prefix + r'(?:add|at|and|put|place)\s+(.+?)\s+(cost\s*(?:co|o|oc)|meijors?|meijers?|myers?|home\s*depot|home\s*depo)(?:[\'’]s)?(?:\s+(?:(?:shopping|grocery)\s+)?list)?[.!?]*$'
        match = re.match(pattern, text, re.IGNORECASE)
    if not match:
        return None
    item = re.sub(r'\s+', ' ', match.group(1)).strip(' .,!?:;')
    list_name = re.sub(r'\s+', ' ', match.group(2)).lower()
    if not item or len(item) > 200:
        return None
    return item, TODO_LISTS[list_name]


def add_todo_item(item, entity_id, ha_token):
    payload = json.dumps({'entity_id': entity_id, 'item': item}).encode()
    request(
        HA_URL + '/api/services/todo/add_item',
        method='POST',
        headers={'Authorization': 'Bearer ' + ha_token, 'Content-Type': 'application/json'},
        data=payload,
        timeout=15,
    )


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == '/panel/action':
            if not panel_authorized(self.headers.get('Authorization')):
                return self.respond(401, {'error': 'unauthorized'})
            try:
                length = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                return self.respond(400, {'error': 'invalid_length'})
            if length < 1 or length > 8192:
                return self.respond(413, {'error': 'action_body_too_large'})
            body = self.rfile.read(length)
            if len(body) != length:
                return self.respond(400, {'error': 'incomplete_body'})
            try:
                status, payload = post_panel(self.path, body, self.client_address[0])
                return self.respond(status, payload)
            except PanelError as exc:
                return self.respond(exc.status, {'error': exc.code})
        if self.path != '/voice-command':
            return self.respond(404, {'error': 'not_found'})
        if not any(hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + t) for t in (TOKEN, FIRE7_TOKEN) if t):
            return self.respond(401, {'error': 'unauthorized'})
        try:
            if not policy_allows():
                return self.respond(403, {'error': 'global_mute_active'})
        except Exception:
            return self.respond(503, {'error': 'policy_unavailable'})
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            return self.respond(400, {'error': 'invalid_length'})
        if length <= 0 or length > MAX_BODY:
            return self.respond(413, {'error': 'audio_request_size_invalid'})
        media_type = self.headers.get('Content-Type', '')
        if not media_type.lower().startswith('multipart/form-data;') or 'boundary=' not in media_type.lower():
            return self.respond(415, {'error': 'multipart_required'})
        body = self.rfile.read(length)
        if len(body) != length:
            return self.respond(400, {'error': 'incomplete_audio'})
        try:
            transcript_json = json.loads(request(
                'http://127.0.0.1:8765/transcribe',
                method='POST',
                headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': media_type},
                data=body,
                timeout=45,
            ))
            transcript = transcript_json.get('text', '').strip()
            if not transcript:
                return self.respond(200, {'text': '', 'ha': None, 'result': 'empty_transcript'})
            # Recheck policy immediately before initiating HA actions.
            if not policy_allows():
                return self.respond(403, {'error': 'global_mute_active'})
            ha_token = HA_TOKEN_PATH.read_text().strip()
            if not ha_token:
                raise RuntimeError('missing_ha_token')
            todo = grocery_command(transcript)
            if todo:
                item, entity_id = todo
                add_todo_item(item, entity_id, ha_token)
                list_name = entity_id.removeprefix('todo.').replace('_', ' ').title()
                return self.respond(200, {
                    'text': transcript,
                    'processing_seconds': transcript_json.get('processing_seconds'),
                    'ha': {
                        'response_type': 'success',
                        'speech': f'Added {item} to your {list_name} list.',
                        'conversation_id': None,
                    },
                })
            payload = json.dumps({'text': transcript, 'language': 'en'}).encode()
            ha_json = json.loads(request(
                HA_URL + '/api/conversation/process',
                method='POST',
                headers={'Authorization': 'Bearer ' + ha_token, 'Content-Type': 'application/json'},
                data=payload,
                timeout=25,
            ))
            ha_response = ha_json.get('response') or {}
            return self.respond(200, {
                'text': transcript,
                'processing_seconds': transcript_json.get('processing_seconds'),
                'ha': {
                    'response_type': ha_response.get('response_type'),
                    'speech': ((ha_response.get('speech') or {}).get('plain') or {}).get('speech', ''),
                    'conversation_id': ha_json.get('conversation_id'),
                },
            })
        except urllib.error.HTTPError as exc:
            # No upstream response body or token is leaked to clients.
            if exc.code in (401, 403):
                return self.respond(502, {'error': 'upstream_auth_failed'})
            return self.respond(502, {'error': 'upstream_http_failure', 'status': exc.code})
        except Exception as exc:
            print('Sonic HA bridge error:', type(exc).__name__, flush=True)
            return self.respond(502, {'error': 'upstream_unavailable'})

    def do_GET(self):
        if self.path in ('/panel/config', '/panel/states', '/panel/health'):
            if not panel_authorized(self.headers.get('Authorization')):
                return self.respond(401, {'error': 'unauthorized'})
            try:
                status, payload = get_panel(self.path)
                return self.respond(status, payload)
            except PanelError as exc:
                return self.respond(exc.status, {'error': exc.code})
        return self.respond(404, {'error': 'not_found'})
    def log_message(self, *args):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8767), Handler).serve_forever(poll_interval=0.3)
