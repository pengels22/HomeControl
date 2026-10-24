from pathlib import Path

APP = Path('02_HCM/www/app.js').read_text()
CSS = Path('02_HCM/www/app.css').read_text()


def test_automation_ui_uses_full_width_rows_and_human_labels():
    assert 'automation-list-header' in APP
    assert 'automation-list' in CSS
    assert 'humanStatus' in APP
    assert 'word-break: normal' in CSS


def test_automation_routes_are_identity_based_and_detail_first():
    assert 'routeSource = openAutomation' in APP
    assert 'renderAutomationDetailPage("staged"' in APP
    assert 'renderAutomationDetailPage("native"' in APP
    assert 'data-edit-route' in APP
    assert 'data-save-route-native' in APP
    assert 'data-open-automation' in APP


def test_staged_and_native_controls_remain_distinct():
    assert 'data-staged-toggle' in APP
    assert 'data-automation-toggle' in APP
    assert 'HA runtime snapshot' in APP
