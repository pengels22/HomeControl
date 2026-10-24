"""Native-style declarative PNL display model shared by simulator and firmware.

The module produces bounded render frames rather than HTML. An LVGL adapter can
map the same frames to widgets; the desktop preview uses the same card geometry
and state resolution rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from importlib import import_module

dashboard = import_module('05_PNL.dashboard')

DISPLAY_WIDTH = 1024
DISPLAY_HEIGHT = 600
LOCAL_ALIASES = ('local.lux', 'local.occupancy', 'local.temp', 'local.humidity')


@dataclass
class PanelDisplayState:
    room: str = 'Panel'
    connected: bool = True
    microphone_muted: bool = True
    local: dict[str, Any] = field(default_factory=lambda: {'lux': None, 'occupancy': None, 'temp': None, 'humidity': None})
    remote: dict[str, dict[str, Any]] = field(default_factory=dict)


class DisplayEngine:
    def __init__(self):
        self._last_good: dict[str, Any] | None = None
        self.layout_sha256: str | None = None
        self.page = 0

    def load_layout(self, layout: dict[str, Any]) -> str:
        compiled = dashboard.compile_dashboard(layout)
        self._last_good = compiled['layout']
        self.layout_sha256 = compiled['sha256']
        self.page = min(self.page, len(self._last_good['pages']) - 1)
        return self.layout_sha256

    def load_or_fallback(self, layout: dict[str, Any] | None) -> str:
        if layout is not None:
            try:
                return self.load_layout(layout)
            except dashboard.DashboardError:
                pass
        if self._last_good is None:
            return self.load_layout({'version': 1, 'theme': 'dark', 'pages': [{'id': 'main', 'title': 'Main', 'cards': []}]})
        return self.layout_sha256 or ''

    @property
    def layout(self) -> dict[str, Any]:
        if self._last_good is None:
            self.load_or_fallback(None)
        return self._last_good

    def _value(self, reference: str | None, state: PanelDisplayState) -> tuple[Any, bool]:
        if reference in LOCAL_ALIASES:
            return state.local.get(reference.split('.', 1)[1]), True
        item = state.remote.get(reference or '', {})
        return item.get('state'), bool(state.connected and item.get('available', True))

    def render_frame(self, state: PanelDisplayState, *, clock: str | None = None) -> dict[str, Any]:
        layout = self.layout
        page = layout['pages'][self.page]
        cards = []
        for card in page['cards']:
            reference = card.get('entity')
            value, available = self._value(reference, state)
            if card['type'] == 'entities':
                refs = card.get('entities') if isinstance(card.get('entities'), list) else list(state.remote)
                rows = []
                for ref in refs:
                    row_value, row_available = self._value(ref, state)
                    rows.append({'entity': ref, 'value': row_value, 'available': row_available, 'writable': bool(state.connected and state.remote.get(ref, {}).get('writable'))})
                value = rows
                available = state.connected
            cards.append({**card, 'value': value, 'available': available, 'remote_action_enabled': bool(available and state.connected and card['type'] not in {'entity', 'entities'} or available and state.connected and state.remote.get(reference, {}).get('writable'))})
        return {'width': DISPLAY_WIDTH, 'height': DISPLAY_HEIGHT, 'theme': layout.get('theme', 'dark'), 'header': {'room': state.room, 'connected': state.connected, 'microphone_muted': state.microphone_muted, 'clock': clock}, 'page': {'id': page['id'], 'title': page['title'], 'cards': cards}, 'page_index': self.page, 'page_count': len(layout['pages']), 'layout_sha256': self.layout_sha256}

    def set_page(self, page: int) -> None:
        if not 0 <= page < len(self.layout['pages']):
            raise ValueError('page outside dashboard bounds')
        self.page = page
