from importlib import import_module

import pytest


dashboard = import_module('05_PNL.dashboard')


def layout(card_type='entity'):
    card = {'id': 'card-1', 'type': card_type, 'title': 'Temperature',
            'bounds': {'x': 0, 'y': 0, 'w': 320, 'h': 160}}
    if card_type != 'entities':
        card['entity'] = 'local.temp'
    else:
        card['entities'] = 'area.current'
    return {'version': 1, 'pages': [{'id': 'main', 'title': 'Main', 'cards': [card]}]}


@pytest.mark.parametrize('card_type', sorted(dashboard.CARD_TYPES))
def test_all_v1_cards_compile(card_type):
    compiled = dashboard.compile_dashboard(layout(card_type))
    assert compiled['preview_only'] is True
    assert len(compiled['sha256']) == 64


def test_invalid_geometry_and_scripts_are_rejected():
    bad = layout(); bad['pages'][0]['cards'][0]['bounds']['w'] = 2000
    with pytest.raises(dashboard.DashboardError):
        dashboard.validate_dashboard(bad)
    bad = layout(); bad['script'] = 'alert(1)'
    with pytest.raises(dashboard.DashboardError):
        dashboard.validate_dashboard(bad)


def test_panel_runtime_is_fail_muted_and_preview_never_actions():
    runtime = dashboard.PNLRuntime('aabbccddeeff')
    assert runtime.global_muted is True
    assert runtime.apply_policy(epoch=1, globally_muted=False, expires=False) is False
    assert runtime.global_muted is True
    runtime.apply_layout(layout('button'))
    preview = runtime.preview({'local.temp': 21})
    assert preview['preview_only'] is True
    assert 'action' not in preview
    assert runtime.telemetry('2026-10-24T12:00:00Z')['sequence'] == 1
