import ast
from importlib import import_module
from pathlib import Path

import pytest


global_config = import_module('08_servises.common.global_config')


def assignment_names(path):
    tree = ast.parse(path.read_text())
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id[0].isupper():
                    names.append(target.id)
    return names


def assignment_lifecycle_tags(path):
    lines = path.read_text().splitlines()
    tree = ast.parse(path.read_text())
    tags = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [
            target.id
            for target in node.targets
            if isinstance(target, ast.Name) and target.id[0].isupper()
        ]
        if not names:
            continue
        comments = []
        idx = node.lineno - 2
        while idx >= 0 and lines[idx].strip().startswith('#'):
            comments.append(lines[idx])
            idx -= 1
        comment = ' '.join(reversed(comments))
        tag = next((item for item in ('REPO', 'USER', 'PROPOSED') if item in comment), None)
        for name in names:
            tags[name] = tag
    return tags


def test_global_configs_load_from_numbered_directories_with_paths():
    for component in ('HCM', 'SIM', 'LCM', 'RCM', 'PNL', 'RMC'):
        cfg = global_config.load_global_config(component)

        assert cfg.component == component
        assert Path(cfg.path).exists()
        assert cfg.as_dict()


def test_global_configs_remain_alphabetized():
    root = global_config.find_repo_root()
    for path in global_config.COMPONENT_FILES.values():
        names = assignment_names(root / path)

        assert names == sorted(names, key=str.casefold), str(path)


def test_global_config_variables_have_lifecycle_classification():
    root = global_config.find_repo_root()
    for path in global_config.COMPONENT_FILES.values():
        tags = assignment_lifecycle_tags(root / path)

        assert tags
        assert all(tags.values()), str(path)


def test_global_config_rejects_invalid_component():
    with pytest.raises(global_config.GlobalConfigError):
        global_config.load_global_config('BAD')


def test_global_config_validation_rejects_bad_type_and_range():
    values = global_config.load_global_config('HCM').as_dict()
    values['Door_Open_Pulse'] = '3000'
    with pytest.raises(global_config.GlobalConfigError):
        global_config._validate('HCM', values)

    values = global_config.load_global_config('HCM').as_dict()
    values['Heartbeat_TCP_Port'] = 6005
    with pytest.raises(global_config.GlobalConfigError):
        global_config._validate('HCM', values)


def test_phase3_pinned_values_are_available():
    hcm = global_config.load_global_config('HCM')
    sim = global_config.load_global_config('SIM')
    rmc = global_config.load_global_config('RMC')

    assert hcm.Heartbeat_TCP_Port == 6004
    assert hcm.Door_Open_Pulse == 3000
    assert sim.Hexa_12V_Restart_Off_Time == 5000
    assert sim.CAN_Bitrate == rmc.CAN_Bitrate == 125000
