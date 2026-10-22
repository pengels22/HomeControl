from pathlib import Path


ROOT = Path(__file__).parents[1]
def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_acm_has_single_authenticated_action_path_and_safe_audit_fields():
    alarm = read("06_ACM/03_Shared/alarm_core.cpp")
    manager = read("06_ACM/03_Shared/keypad_manager.cpp")
    assert "requestWithPin" in alarm
    assert "pins_.authenticate(pin)" in alarm
    assert "PIN_FAILED" in manager
    assert "PIN=" in manager
    assert '"pin"' not in manager.split("PIN_FAILED", 1)[1].split("}", 1)[0]


def test_keypad_transports_all_actions_through_reusable_controller():
    controller = read("06_ACM/02_Keypad/ui_controller.h")
    keypad = read("06_ACM/02_Keypad/main.cpp")
    assert "setActionHandler" in controller
    assert "takePin()" in controller
    for action in ("ARM_HOME", "ARM_AWAY", "DISARM"):
        assert action in controller or action in keypad
    assert "KEYPAD_ACTION" in keypad
    assert "ACTION_RESULT" in keypad


def test_acm_ci_isolated_from_general_ci_for_acm_only_changes():
    workflow = read(".github/workflows/acm-ci.yml")
    general = read(".github/workflows/ci.yml")
    assert "06_ACM/**" in workflow
    assert "paths-ignore:" in general
    assert "06_ACM/**" in general
