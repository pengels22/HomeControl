"""Opt-in, non-energizing hardware readiness checks."""

from importlib import import_module

import pytest

pytestmark = pytest.mark.hardware


def test_physical_test_gate_is_explicit():
    assert import_module('08_servises.common.commissioning').physical_write_allowed(
        {'physical_output_enabled': False}, 'A1'
    ) is False
