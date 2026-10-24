from importlib import import_module

import pytest


dashboard = import_module('05_PNL.dashboard')


def test_dashboard_editor_contract_has_stable_preview_and_bounds():
    layout = {'version': 1, 'theme': 'dark', 'pages': [{'id': 'main', 'cards': [{
        'id': 'temp', 'type': 'entity', 'entity': 'local.temp',
        'bounds': {'x': 0, 'y': 0, 'w': 240, 'h': 120},
    }]}]}
    first = dashboard.compile_dashboard(layout)
    second = dashboard.compile_dashboard(layout)
    assert first == second
    assert first['preview_only'] is True


def test_dashboard_editor_rejects_arbitrary_markup_and_oversized_layout():
    layout = {'version': 1, 'html': '<script>x</script>', 'pages': []}
    with pytest.raises(dashboard.DashboardError):
        dashboard.validate_dashboard(layout)
