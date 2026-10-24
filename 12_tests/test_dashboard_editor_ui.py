from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_panel_editor_is_reachable_and_preview_safe():
    index = (ROOT / '01_HCM/www/index.html').read_text()
    app = (ROOT / '01_HCM/www/app.js').read_text()
    css = (ROOT / '01_HCM/www/app.css').read_text()
    assert 'href="/editor"' in index
    assert 'href="/pnl"' in index
    assert 'Panel Editor' in index
    assert 'renderEditor' in app
    assert '/dashboard-editor' in app
    assert 'data-editor-add-card' in app
    assert 'area.current' in app
    assert 'Preview only' in app
    assert 'Global microphone mute policy' in app
    assert '/pnl-production/admin/devices' in app
    assert '.editor-canvas' in css
    assert '.editor-card' in css
