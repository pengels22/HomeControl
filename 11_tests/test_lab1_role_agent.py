import asyncio
import json
import stat
import subprocess
import sys
import textwrap
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

lab1 = import_module("10_scripts.lab1_role_agent")

OPERATION_ID = "11111111-2222-4333-8444-555555555555"


def real_lab1_state(role="UNASSIGNED"):
    return {
        "device_id": "2ccf675d3414",
        "hostname": "lab1",
        "role": role,
        "simulation": True,
        "physical_outputs_enabled": False,
        "commissioned": False,
    }


def role_payload(role="SIM", operation_id=OPERATION_ID):
    return {
        "op": "set_module_role",
        "operation_id": operation_id,
        "device_id": "2ccf675d3414",
        "requested_role": role,
        "simulation_required": True,
    }


def test_lab1_role_command_updates_role_and_preserves_supervisor_fields():
    state = real_lab1_state(role="UNASSIGNED")

    response = lab1.apply_role_command(state, role_payload("SIM"), request_id=OPERATION_ID)

    assert response["accepted"] is True
    assert response["lab_role"] == "SIM"
    assert state["role"] == "SIM"
    assert state["device_id"] == "2ccf675d3414"
    assert state["hostname"] == "lab1"
    assert state["simulation"] is True
    assert state["physical_outputs_enabled"] is False
    assert state["commissioned"] is False
    assert lab1.heartbeat_state(state, "RCM")["lab_role"] == "SIM"


def test_lab1_atomic_save_preserves_0644_permissions_after_repeated_changes(tmp_path):
    state_path = tmp_path / "module.json"
    state_path.write_text(json.dumps(real_lab1_state()) + "\n")
    state_path.chmod(0o644)

    state = lab1.load_state(state_path)
    lab1.apply_role_command(state, role_payload("RCM"), request_id=OPERATION_ID)
    lab1.save_state_atomic(state_path, state)
    first_stat = state_path.stat()

    second_operation_id = "22222222-3333-4444-8555-666666666666"
    state = lab1.load_state(state_path)
    lab1.apply_role_command(state, role_payload("LCM", second_operation_id), request_id=second_operation_id)
    lab1.save_state_atomic(state_path, state)
    second_stat = state_path.stat()

    assert stat.S_IMODE(first_stat.st_mode) == 0o644
    assert stat.S_IMODE(second_stat.st_mode) == 0o644
    assert first_stat.st_uid == second_stat.st_uid
    assert first_stat.st_gid == second_stat.st_gid
    assert lab1.load_state(state_path)["role"] == "LCM"


@pytest.mark.parametrize("operation_id", [None, "", "not-a-uuid", "11111111-2222-3333-4444", "g1111111-2222-4333-8444-555555555555"])
def test_lab1_role_command_rejects_invalid_operation_ids(operation_id):
    with pytest.raises(lab1.RoleCommandError):
        lab1.apply_role_command(
            real_lab1_state(),
            role_payload("SIM", operation_id),
            request_id=operation_id,
        )


def test_lab1_role_command_rejects_request_id_operation_id_mismatch():
    with pytest.raises(lab1.RoleCommandError, match="mismatch"):
        lab1.apply_role_command(
            real_lab1_state(),
            role_payload("SIM", OPERATION_ID),
            request_id="22222222-3333-4444-8555-666666666666",
        )


def test_lab1_role_command_is_idempotent_for_duplicate_matching_operation():
    state = real_lab1_state()

    lab1.apply_role_command(state, role_payload("LCM"), request_id=OPERATION_ID)
    second = lab1.apply_role_command(state, role_payload("LCM"), request_id=OPERATION_ID)

    assert second["duplicate"] is True
    assert state["role"] == "LCM"


def test_lab1_role_command_rejects_conflicting_duplicate_operation():
    state = real_lab1_state()
    lab1.apply_role_command(state, role_payload("LCM"), request_id=OPERATION_ID)

    with pytest.raises(lab1.RoleCommandError, match="conflicts"):
        lab1.apply_role_command(state, role_payload("SIM"), request_id=OPERATION_ID)

    assert state["role"] == "LCM"


@pytest.mark.parametrize("payload", [
    {"op": "set_relay", "operation_id": OPERATION_ID},
    role_payload("PNL"),
    {**role_payload("LCM"), "simulation_required": False},
    {**role_payload("LCM"), "device_id": "48b02d87db16"},
])
def test_lab1_role_command_rejects_unsafe_payloads(payload):
    with pytest.raises(lab1.RoleCommandError):
        lab1.apply_role_command(real_lab1_state(), payload, request_id=payload.get("operation_id"))


@pytest.mark.parametrize("bad_state", [
    {**real_lab1_state(), "device_id": "48b02d87db16"},
    {**real_lab1_state(), "hostname": "other"},
    {**real_lab1_state(), "simulation": False},
    {**real_lab1_state(), "physical_outputs_enabled": True},
])
def test_lab1_role_command_rejects_unsafe_existing_state(bad_state):
    with pytest.raises(lab1.RoleCommandError):
        lab1.apply_role_command(bad_state, role_payload("SIM"), request_id=OPERATION_ID)


def test_handle_command_file_accepts_existing_command_frame(tmp_path):
    state_path = tmp_path / "module.json"
    payload_path = tmp_path / "command.json"
    state_path.write_text(json.dumps(real_lab1_state()) + "\n")
    payload_path.write_text(json.dumps({
        "type": "command",
        "request_id": OPERATION_ID,
        "payload": role_payload("RCM", OPERATION_ID),
    }))

    response = lab1.handle_command_file(state_path, payload_path)

    assert response["accepted"] is True
    assert lab1.load_state(state_path)["role"] == "RCM"


def _write_original_lab1_agent(path: Path) -> None:
    path.write_text(textwrap.dedent(
        '''
        import asyncio
        import json
        from pathlib import Path


        async def send_frame(writer, frame_type, payload, request_id=None):
            writer.sent.append((frame_type, payload, request_id))


        async def session(context, stop):
            writer = context.writer
            while not stop.is_set():
                response = await context.next_response()
                kind = response["type"]
                if kind == "command":
                    await send_frame(
                        writer,
                        "command_ack",
                        {
                            "ok": False,
                            "error": "simulation_commands_disabled",
                        },
                        response.get("request_id"),
                    )
                    print("HCM command rejected: simulation-only", flush=True)
                    continue
                stop.set()
        '''
    ).lstrip())


def _load_patched_lab_agent(path: Path, module_dir: Path):
    sys.path.insert(0, str(module_dir))
    spec = spec_from_file_location("patched_lab_agent", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Writer:
    def __init__(self):
        self.sent = []


class _Context:
    def __init__(self, responses, state_path):
        self.writer = _Writer()
        self.responses = list(responses)
        self.state_path = state_path
        self.state = None

    async def next_response(self):
        if self.responses:
            return self.responses.pop(0)
        return {"type": "idle"}


def test_lab1_agent_patch_applies_and_accepts_set_module_role(tmp_path):
    target_dir = tmp_path / "opt" / "homecontrol-lab"
    target_dir.mkdir(parents=True)
    agent_path = target_dir / "lab_agent.py"
    state_path = target_dir / "state" / "module.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(real_lab1_state()) + "\n")
    (target_dir / "lab1_role_agent.py").write_text(Path(lab1.__file__).read_text())
    _write_original_lab1_agent(agent_path)

    result = subprocess.run(
        ["patch", "-p1", "-i", str(Path("10_scripts/lab1_agent_set_module_role.patch").resolve())],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    module = _load_patched_lab_agent(agent_path, target_dir)
    context = _Context(
        [
            {
                "type": "command",
                "request_id": OPERATION_ID,
                "payload": role_payload("SIM", OPERATION_ID),
            },
        ],
        state_path,
    )
    stop = asyncio.Event()

    async def stop_after_command():
        await module.session(context, stop)

    async def set_stop():
        while context.responses:
            await asyncio.sleep(0)
        stop.set()

    async def run_session():
        await asyncio.gather(stop_after_command(), set_stop())

    asyncio.run(run_session())

    assert context.writer.sent == [
        (
            "command_ack",
            {
                "ok": True,
                "accepted": True,
                "operation_id": OPERATION_ID,
                "lab_role": "SIM",
                "simulation": True,
                "physical_outputs_enabled": False,
            },
            OPERATION_ID,
        )
    ]
    assert lab1.load_state(state_path)["role"] == "SIM"
    assert context.state["role"] == "SIM"


def test_patched_lab1_agent_rejects_non_role_commands(tmp_path):
    target_dir = tmp_path / "opt" / "homecontrol-lab"
    target_dir.mkdir(parents=True)
    agent_path = target_dir / "lab_agent.py"
    state_path = target_dir / "state" / "module.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(real_lab1_state()) + "\n")
    (target_dir / "lab1_role_agent.py").write_text(Path(lab1.__file__).read_text())
    _write_original_lab1_agent(agent_path)

    result = subprocess.run(
        ["patch", "-p1", "-i", str(Path("10_scripts/lab1_agent_set_module_role.patch").resolve())],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    module = _load_patched_lab_agent(agent_path, target_dir)
    request_id = "22222222-3333-4444-8555-666666666666"
    context = _Context(
        [
            {
                "type": "command",
                "request_id": request_id,
                "payload": {"op": "set_relay", "channel": "A1", "value": True},
            },
        ],
        state_path,
    )
    stop = asyncio.Event()

    async def set_stop():
        while context.responses:
            await asyncio.sleep(0)
        stop.set()

    async def run_session():
        await asyncio.gather(module.session(context, stop), set_stop())

    asyncio.run(run_session())

    assert context.writer.sent == [
        (
            "command_ack",
            {
                "ok": False,
                "error": "simulation_commands_disabled",
            },
            request_id,
        )
    ]
    assert lab1.load_state(state_path)["role"] == "UNASSIGNED"
