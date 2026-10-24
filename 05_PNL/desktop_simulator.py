"""Launchable desktop PNL preview using the same display-frame contract."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from importlib import import_module

display = import_module('05_PNL.display_engine')
dashboard = import_module('05_PNL.dashboard')


def fixture(name: str) -> dict:
    rooms = {'living': 'Living Room', 'kitchen': 'Kitchen', 'bedroom': 'Bedroom'}
    return {'room': rooms.get(name, rooms['living']), 'local': {'lux': 340, 'occupancy': True, 'temp': 21.5, 'humidity': 43}, 'remote': {'light.main': {'state': 'ON', 'available': True, 'writable': True}, 'climate.home': {'state': {'temperature': 21, 'target': 22, 'mode': 'HEAT'}, 'available': True, 'writable': True}}}


def preview_frame(room: str = 'living', connected: bool = True) -> dict:
    engine = display.DisplayEngine()
    engine.load_layout({'version': 1, 'theme': 'dark', 'pages': [{'id': 'main', 'title': 'Room', 'cards': [
        {'id': 'temp', 'type': 'entity', 'title': 'Temperature', 'entity': 'local.temp', 'bounds': {'x': 24, 'y': 90, 'w': 230, 'h': 130}},
        {'id': 'humidity', 'type': 'entity', 'title': 'Humidity', 'entity': 'local.humidity', 'bounds': {'x': 270, 'y': 90, 'w': 230, 'h': 130}},
        {'id': 'lights', 'type': 'button', 'title': 'Main Light', 'entity': 'light.main', 'bounds': {'x': 516, 'y': 90, 'w': 230, 'h': 130}},
        {'id': 'thermostat', 'type': 'thermostat', 'title': 'Thermostat', 'entity': 'climate.home', 'bounds': {'x': 762, 'y': 90, 'w': 230, 'h': 250}},
    ]}]})
    values = fixture(room)
    values['connected'] = connected
    return engine.render_frame(display.PanelDisplayState(**values))


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == '/frame':
            body = json.dumps(preview_frame()).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = (Path(__file__).with_name('www').joinpath('index.html').read_bytes())
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description='HomeControl PNL desktop preview')
    parser.add_argument('--host', default='127.0.0.1'); parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), PreviewHandler).serve_forever()


if __name__ == '__main__':
    main()
