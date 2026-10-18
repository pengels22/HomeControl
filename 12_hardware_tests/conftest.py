import os
import pytest


def pytest_collection_modifyitems(config, items):
    if os.getenv('HCM_HARDWARE_TESTS') == '1' and os.getenv('HCM_HARDWARE_TARGET'):
        return
    skip = pytest.mark.skip(reason='hardware tests require HCM_HARDWARE_TESTS=1 and HCM_HARDWARE_TARGET')
    for item in items:
        if 'hardware' in item.keywords:
            item.add_marker(skip)
