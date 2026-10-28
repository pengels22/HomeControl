#!/usr/bin/env python3
"""Apply the reviewed panel integration to staging copies only.

The script refuses an already-integrated source and checks that the existing
voice routes are present before writing either candidate file.
"""
from __future__ import annotations

import sys
from pathlib import Path


IMPORT = "from panel_api import PanelError, get_panel, panel_authorized, post_panel\n"
POST_MARKER = "    def do_POST(self):\n"
GET_MARKER = "    def do_GET(self):\n"
POST_BLOCK = '''    def do_POST(self):
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
'''
GET_BLOCK = '''    def do_GET(self):
        if self.path in ('/panel/config', '/panel/states', '/panel/health'):
            if not panel_authorized(self.headers.get('Authorization')):
                return self.respond(401, {'error': 'unauthorized'})
            try:
                status, payload = get_panel(self.path)
                return self.respond(status, payload)
            except PanelError as exc:
                return self.respond(exc.status, {'error': exc.code})
        return self.respond(404, {'error': 'not_found'})
'''
CADDY_BLOCK = '''    # sonic-panel-api-installed
    # Authentication is performed by the bridge with SONIC_FIRE7_TOKEN.
    # Do not use /authorize here: it is microphone-mute-gated.
    handle /panel/config {
        reverse_proxy 127.0.0.1:8767
    }
    handle /panel/states {
        reverse_proxy 127.0.0.1:8767
    }
    handle /panel/action {
        reverse_proxy 127.0.0.1:8767
    }
    handle /panel/health {
        reverse_proxy 127.0.0.1:8767
    }
'''


def apply_bridge(path: Path) -> None:
    text = path.read_text()
    if IMPORT in text or "sonic-panel-api-installed" in text:
        raise SystemExit("refusing already-integrated source")
    required = [POST_MARKER, GET_MARKER, "if self.path != '/voice-command':", "http://127.0.0.1:8765/transcribe"]
    if any(marker not in text for marker in required):
        raise SystemExit("bridge source does not match the reviewed Sonic layout")
    text = text.replace("from pathlib import Path\n", "from pathlib import Path\n" + IMPORT, 1)
    post_start = text.index(POST_MARKER)
    get_start = text.index(GET_MARKER, post_start)
    old_post = text[post_start:get_start]
    text = text[:post_start] + POST_BLOCK + old_post[len(POST_MARKER):] + text[get_start:]
    get_start = text.index(GET_MARKER, post_start)
    log_start = text.index("    def log_message", get_start)
    old_get = text[get_start:log_start]
    text = text[:get_start] + GET_BLOCK + text[log_start:]
    if "if self.path != '/voice-command':" not in text or "http://127.0.0.1:8765/transcribe" not in text:
        raise SystemExit("voice route preservation check failed")
    path.write_text(text)


def apply_caddy(path: Path) -> None:
    text = path.read_text()
    if "sonic-panel-api-installed" in text:
        raise SystemExit("refusing already-integrated Caddyfile")
    anchor = "    # sonic-ha-bridge-installed\n    handle /voice-command {"
    if text.count(anchor) != 1:
        raise SystemExit("expected exactly one Sonic voice route anchor")
    text = text.replace("    # sonic-ha-bridge-installed\n", CADDY_BLOCK, 1)
    if text.count("handle /panel/config") != 1 or text.count("forward_auth 127.0.0.1:8766") != 2:
        raise SystemExit("Caddy route preservation check failed")
    path.write_text(text)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: apply_panel_integration.py BRIDGE_COPY CADDY_COPY")
    apply_bridge(Path(sys.argv[1]))
    apply_caddy(Path(sys.argv[2]))
