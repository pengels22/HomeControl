from importlib import import_module

import pytest


display = import_module('05_PNL.display_engine')
simulator = import_module('05_PNL.desktop_simulator')


def layout():
    return {'version': 1, 'theme': 'dark', 'pages': [{'id': 'main', 'title': 'Room', 'cards': [
        {'id': 'temp', 'type': 'entity', 'entity': 'local.temp', 'bounds': {'x': 24, 'y': 24, 'w': 240, 'h': 120}},
        {'id': 'light', 'type': 'button', 'entity': 'light.main', 'bounds': {'x': 280, 'y': 24, 'w': 240, 'h': 120}},
        {'id': 'all', 'type': 'entities', 'entities': 'area.current', 'bounds': {'x': 536, 'y': 24, 'w': 440, 'h': 300}},
    ]}]}


def test_display_uses_local_aliases_and_marks_remote_unavailable_offline():
    engine = display.DisplayEngine(); engine.load_layout(layout())
    state = display.PanelDisplayState(room='Kitchen', connected=False, local={'temp': 22, 'lux': 10, 'occupancy': True, 'humidity': 40}, remote={'light.main': {'state': 'ON', 'available': True}})
    frame = engine.render_frame(state)
    assert frame['width'] == 1024 and frame['height'] == 600
    assert frame['header']['room'] == 'Kitchen'
    assert frame['page']['cards'][0]['value'] == 22
    assert frame['page']['cards'][1]['available'] is False
    assert frame['page']['cards'][1]['remote_action_enabled'] is False


def test_invalid_update_preserves_last_good_layout_and_pages_are_bounded():
    engine = display.DisplayEngine(); sha = engine.load_layout(layout())
    assert engine.load_or_fallback({'version': 1, 'pages': []}) == sha
    with pytest.raises(ValueError):
        engine.set_page(2)


def test_desktop_fixture_is_full_width_and_has_no_sidebar_or_scenes():
    frame = simulator.preview_frame('bedroom')
    html = (simulator.Path(simulator.__file__).with_name('www').joinpath('index.html')).read_text()
    assert frame['width'] == 1024
    assert frame['header']['room'] == 'Bedroom'
    assert 'sidebar' not in html.lower()
    assert 'Scenes' not in html
