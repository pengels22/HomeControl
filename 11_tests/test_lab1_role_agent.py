from importlib import import_module
from pathlib import Path

import pytest

lab1 = import_module("10_scripts.lab1_role_agent")


def test_lab1_role_command_applies_safely(tmp_path):
    state_path = tmp_path / "module.json"
    state = lab1.load_state(state_path)
    response = lab1.apply_role_command(state, {
        "op": "set_module_role",
        "operation_id": "11111111-2222-4333-8444-555555555555",
        "device_id": "2ccf675d3414",
        "requested_role": "SIM",
        "simulation_required": True,
    })
    lab1.save_state_atomic(state_path, state)

    stored = lab1.load_state(state_path)
    assert response["accepted"] is True
    assert stored["lab_role"] == "SIM"
    assert stored["simulation"] is True
    assert stored["physical_outputs_enabled"] is False
    assert stored["commissioned_local"] is False


@pytest.mark.parametrize("payload", [
    {"op": "set_relay"},
    {
        "op": "set_module_role",
        "operation_id": "11111111-2222-4333-8444-555555555555",
        "device_id": "48b02d87db16",
        "requested_role": "SIM",
        "simulation_required": True,
    },
    {
        "op": "set_module_role",
        "operation_id": "11111111-2222-4333-8444-555555555555",
        "device_id": "2ccf675d3414",
        "requested_role": "PNL",
        "simulation_required": True,
    },
    {
        "op": "set_module_role",
        "operation_id": "11111111-2222-4333-8444-555555555555",
        "device_id": "2ccf675d3414",
        "requested_role": "LCM",
        "simulation_required": False,
    },
])
def test_lab1_role_command_rejects_unsafe_payloads(payload):
    with pytest.raises(lab1.RoleCommandError):
        lab1.apply_role_command(lab1.load_state(Path("/missing")), payload)


def test_lab1_role_command_is_idempotent_for_duplicate_operation():
    state = lab1.load_state(Path("/missing"))
    payload = {
        "op": "set_module_role",
        "operation_id": "11111111-2222-4333-8444-555555555555",
        "device_id": "2ccf675d3414",
        "requested_role": "LCM",
        "simulation_required": True,
    }

    lab1.apply_role_command(state, payload)
    second = lab1.apply_role_command(state, {**payload, "requested_role": "SIM"})

    assert second["duplicate"] is True
    assert state["lab_role"] == "LCM"
