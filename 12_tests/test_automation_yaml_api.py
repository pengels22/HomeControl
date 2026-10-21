import importlib
import pytest

api = importlib.import_module('01_HCM.automation_api')


def test_definition_accepts_multiline_yaml_and_applies_editor_name():
    result = api._definition({
        'name': 'Edited name',
        'yaml': '''enabled: true\nmode: single\ntriggers:\n  - type: conversation\n    phrases: [hello]\nactions:\n  - type: stop\n''',
    })
    assert result['name'] == 'Edited name'
    assert result['triggers'][0]['type'] == 'conversation'


def test_definition_rejects_invalid_yaml():
    with pytest.raises(ValueError, match='Invalid HCM YAML'):
        api._definition({'yaml': 'triggers: [\n'})
