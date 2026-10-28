"""Bounded declarative dashboard interpreter used by PNL simulator and firmware contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

CARD_TYPES = {'button', 'slider', 'entity', 'entities', 'thermostat'}
MAX_PAGES = 8
MAX_CARDS = 160
MAX_TEXT = 120


class DashboardError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise DashboardError(f'{field} must be a non-empty bounded string')
    return value.strip()


def validate_dashboard(layout: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(layout, dict) or set(layout) - {'version', 'theme', 'pages'}:
        raise DashboardError('dashboard must be an object with an allowlisted shape')
    if layout.get('version') != 1:
        raise DashboardError('dashboard version must be 1')
    pages = layout.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise DashboardError('dashboard pages are outside bounds')
    total = 0
    clean_pages = []
    for page in pages:
        if not isinstance(page, dict) or set(page) - {'id', 'title', 'cards'}:
            raise DashboardError('page contains unsupported fields')
        page_id = _text(page.get('id'), 'page.id')
        title = _text(page.get('title', page_id), 'page.title')
        cards = page.get('cards')
        if not isinstance(cards, list):
            raise DashboardError('page.cards must be a list')
        clean_cards = []
        for card in cards:
            total += 1
            if total > MAX_CARDS or not isinstance(card, dict):
                raise DashboardError('dashboard card count or shape is invalid')
            if set(card) - {'id', 'type', 'title', 'entity', 'entities', 'items', 'icon', 'action', 'bounds', 'visible_if'}:
                raise DashboardError('card contains unsupported fields')
            card_type = card.get('type')
            if card_type not in CARD_TYPES:
                raise DashboardError('unsupported dashboard card type')
            card_id = _text(card.get('id'), 'card.id')
            bounds = card.get('bounds', {})
            if not isinstance(bounds, dict) or set(bounds) - {'x', 'y', 'w', 'h'}:
                raise DashboardError('card.bounds is invalid')
            if any(not isinstance(bounds.get(k), int) for k in ('x', 'y', 'w', 'h')):
                raise DashboardError('card.bounds must use integer geometry')
            if not (0 <= bounds['x'] < 1024 and 0 <= bounds['y'] < 600 and 1 <= bounds['w'] <= 1024 and 1 <= bounds['h'] <= 600):
                raise DashboardError('card.bounds exceed 1024x600 panel geometry')
            if bounds['x'] + bounds['w'] > 1024 or bounds['y'] + bounds['h'] > 600:
                raise DashboardError('card.bounds exceed panel geometry')
            if card_type in {'entity', 'button', 'slider', 'thermostat'} and not isinstance(card.get('entity'), str):
                raise DashboardError(f'{card_type} requires an entity reference')
            if card_type == 'entities' and not (isinstance(card.get('entities'), list) or card.get('entities') == 'area.current'):
                raise DashboardError('entities requires an allowlisted selector')
            if 'items' in card and (not isinstance(card['items'], list) or any(not isinstance(item, dict) for item in card['items'])):
                raise DashboardError('card.items must be a list of objects')
            clean_cards.append(copy.deepcopy(card))
        clean_pages.append({'id': page_id, 'title': title, 'cards': clean_cards})
    return {'version': 1, 'theme': layout.get('theme', 'default'), 'pages': clean_pages}


def compile_dashboard(layout: dict[str, Any]) -> dict[str, Any]:
    clean = validate_dashboard(layout)
    encoded = json.dumps(clean, sort_keys=True, separators=(',', ':')).encode()
    return {'layout': clean, 'sha256': hashlib.sha256(encoded).hexdigest(), 'preview_only': True}


class PNLRuntime:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.sequence = 0
        self.local = {'lux': None, 'occupancy': None, 'temp': None, 'humidity': None}
        self.global_muted = True
        self.policy_epoch = 0
        self.layout = None

    def apply_policy(self, *, epoch: int, globally_muted: bool, expires: bool = True):
        if epoch < self.policy_epoch or not expires:
            self.global_muted = True
            return False
        self.policy_epoch = epoch
        self.global_muted = bool(globally_muted)
        return True

    def apply_layout(self, layout: dict[str, Any]) -> str:
        compiled = compile_dashboard(layout)
        self.layout = compiled
        return compiled['sha256']

    def telemetry(self, timestamp: str) -> dict[str, Any]:
        self.sequence += 1
        return {'device_id': self.device_id, 'sequence': self.sequence,
                'timestamp': timestamp, 'local': dict(self.local),
                'microphone_muted': self.global_muted}

    def preview(self, states: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.layout:
            raise DashboardError('no last-good layout is loaded')
        return {'preview_only': True, 'microphone_muted': self.global_muted,
                'layout': copy.deepcopy(self.layout['layout']), 'states': dict(states or {})}
