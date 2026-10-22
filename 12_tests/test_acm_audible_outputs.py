from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACM = (ROOT / "06_ACM/01_ACM/main.cpp").read_text()
KEYPAD = (ROOT / "06_ACM/02_Keypad/main.cpp").read_text()
MANAGER = (ROOT / "06_ACM/03_Shared/keypad_manager.cpp").read_text()


def relay_policy(siren_flags, state, commanded=None):
    commanded = list(commanded or [False] * len(siren_flags))
    for index, siren in enumerate(siren_flags):
        if siren:
            commanded[index] = state == "TRIGGERED"
    return commanded


def test_only_configured_sirens_are_selected_and_contacts_survive():
    assert relay_policy([True, False, True], "TRIGGERED", [False, True, False]) == [True, True, True]
    assert relay_policy([True, False, True], "DISARMED", [True, True, True]) == [False, True, False]


def test_runtime_contains_active_low_and_config_change_reconciliation():
    assert "MCP_GPIOB, value" in ACM
    assert "if (!configured) setRelay(i, false)" in ACM
    assert "configStore.relay(i).siren" in ACM


def test_keypad_siren_commands_and_reconnect_reconciliation_exist():
    assert 'LOCAL_SIREN_ON' in MANAGER
    assert 'LOCAL_SIREN_OFF' in MANAGER
    assert "reconcileSiren(k)" in MANAGER
    assert "digitalWrite(acm_hw::KEYPAD_SIREN,LOW)" in KEYPAD
    assert "digitalWrite(acm_hw::KEYPAD_SIREN,HIGH)" in KEYPAD


def test_countdown_chirps_once_per_changed_delay_second():
    assert "lastChirpedCountdown" in KEYPAD
    assert "snapshot.state==AlarmState::ARMING_DELAY||snapshot.state==AlarmState::ENTRY_DELAY" in KEYPAD
    assert "toneFeedback(880,100)" in KEYPAD
    assert "lastChirpedCountdown=0xffffffff;stopTone()" in KEYPAD


def test_panic_is_edge_debounced_without_release_wait():
    assert "void readPanic()" in KEYPAD
    assert "panicAsserted" in KEYPAD
    assert "while(digitalRead(acm_hw::KEYPAD_PANIC)==LOW)" not in KEYPAD
    assert 'KEYPAD_EVENT' in KEYPAD and 'PANIC' in KEYPAD
