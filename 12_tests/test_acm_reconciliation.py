from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACM = (ROOT / "06_ACM/01_ACM/main.cpp").read_text()
CORE = (ROOT / "06_ACM/03_Shared/alarm_core.cpp").read_text()
CONFIG = (ROOT / "06_ACM/03_Shared/config_store.h").read_text()
MANAGER = (ROOT / "06_ACM/03_Shared/keypad_manager.cpp").read_text()
KEYPAD = (ROOT / "06_ACM/02_Keypad/main.cpp").read_text()


def test_local_inputs_use_stable_250ms_debounce_state():
    assert "localRawChangedAt[24]" in ACM
    assert "localDebouncedOpen[24]" in ACM
    assert "static_cast<uint32_t>(now - localRawChangedAt[i]) >= 250" in ACM
    assert "static_cast<uint32_t>(now - localRawChangedAt[index]) >= 250" in ACM


def test_faulted_sensor_is_not_reported_open_or_qualified():
    assert "sensors_[i].open && !sensors_[i].failed" in CORE
    assert "!open || failed" in CORE


def test_keypad_snapshot_requires_all_eight_states():
    assert "uint8_t count=0" in MANAGER
    assert "if(count==8)receiveSnapshot" in MANAGER


def test_keypad_capacity_fits_the_eighty_slot_pool():
    assert "MAX_KEYPADS=7" in CONFIG
    assert "MAX_LOGICAL_SENSORS=80" in (ROOT / "06_ACM/03_Shared/alarm_core.h").read_text()


def test_hello_direction_matches_pinned_keypad_protocol():
    assert "sendFrame(clients_[i],acm_protocol::HELLO_KEYPAD" in MANAGER
    assert 'frame.indexOf("\\\"type\\\":\\\"HELLO_KEYPAD\\\"")' in KEYPAD
    assert "sendFrame(acm,acm_protocol::HELLO_ACM" in KEYPAD
