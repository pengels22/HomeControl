from importlib import import_module


infra = import_module("08_servises.common.module_infra")


def select(controller, bank, start=0):
    bit = 1 << (bank - 1)
    controller.sample(0, 0, 0, start)
    controller.sample(bit, 0, 0, start + 1)
    return controller.sample(bit, 0, 0, start + 251)


def test_bank_selection_is_exclusive_and_maps_all_four_banks():
    controller = infra.RCMBankController(lambda *_: None)
    assert select(controller, 1)["active_bank"] == 1
    controller.sample(0, 0, 0, 1000)
    assert select(controller, 2, 1250)["active_bank"] == 2
    controller.sample(0, 0, 0, 2250)
    assert select(controller, 3, 2500)["active_bank"] == 3
    controller.sample(0, 0, 0, 3500)
    assert select(controller, 4, 3750)["active_bank"] == 4


def test_raw_active_low_mapping_matches_mcp1_mcp2_contract():
    controller = infra.RCMBankController(lambda *_: None)
    controller.update_from_raw(0x0F, 0xFF, 0xFF, 0)
    controller.update_from_raw(0b1110, 0xFF, 0xFF, 1)
    status = controller.update_from_raw(0b1110, 0xFF, 0xFF, 251)
    assert status["active_bank"] == 1


def test_selector_hold_does_not_retrigger_or_extend_timeout():
    controller = infra.RCMBankController(lambda *_: None)
    assert select(controller, 1)["last_bank_activity_ms"] == 251
    assert controller.sample(1, 0, 0, 5250)["active_bank"] == 1
    assert controller.sample(1, 0, 0, 5251)["active_bank"] == 0


def test_selector_bounce_shorter_than_debounce_is_ignored():
    controller = infra.RCMBankController(lambda *_: None)
    controller.sample(0, 0, 0, 0)
    controller.sample(1, 0, 0, 100)
    assert controller.sample(0, 0, 0, 200)["active_bank"] == 0


def test_startup_asserted_selector_requires_release_before_selection():
    controller = infra.RCMBankController(lambda *_: None)
    controller.sample(1, 0, 0, 0)
    assert controller.sample(1, 0, 0, 500)["active_bank"] == 0
    controller.sample(0, 0, 0, 1000)
    controller.sample(0, 0, 0, 1250)
    assert controller.sample(1, 0, 0, 1500)["active_bank"] == 0
    assert controller.sample(1, 0, 0, 1750)["active_bank"] == 1


def test_conflicting_selectors_clear_bank_and_require_all_release():
    controller = infra.RCMBankController(lambda *_: None)
    assert select(controller, 1)["active_bank"] == 1
    controller.sample(0b0011, 0, 0, 1000)
    conflict = controller.sample(0b0011, 0, 0, 1251)
    assert conflict["active_bank"] == 0
    assert conflict["selector_conflict"] is True
    controller.sample(0, 0, 0, 1500)
    assert controller.sample(0, 0, 0, 1751)["selector_conflict"] is False
    assert controller.sample(1, 0, 0, 2000)["active_bank"] == 0
    assert controller.sample(1, 0, 0, 2251)["active_bank"] == 1


def test_override_requires_high_requalification_after_bank_selection():
    operations = []
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 1)
    controller.sample(1, 1, 0, 500)
    controller.sample(1, 1, 0, 750)
    assert controller.sample(1, 1, 0, 1000)["operations"] == []
    assert operations == []
    controller.sample(1, 0, 0, 1250)
    controller.sample(1, 0, 0, 1500)
    controller.sample(1, 1, 0, 1750)
    result = controller.sample(1, 1, 0, 2000)
    assert result["operations"] == [{"override": 1, "channel_index": 0, "value": True, "bank": 1, "generation": 1}]
    assert operations == [(0, True)]


def test_override_held_low_during_bank_change_cannot_leak_to_new_bank():
    operations = []
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 1)
    for now in (500, 750, 1000):
        controller.sample(1, 1, 0, now)
    select(controller, 2, 1500)
    for now in (1750, 2000, 2250):
        controller.sample(2, 1, 0, now)
    assert operations == []
    assert controller.status(2250)["override_states"][0] == infra.OverrideState.WAIT_FOR_HIGH


def test_override_bounce_and_held_low_dispatch_exactly_once():
    operations = []
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 2)
    for now in (500, 750, 1000):
        controller.sample(2, 0, 0, now)
    controller.sample(2, 1, 0, 1100)
    assert controller.sample(2, 0, 0, 1200)["operations"] == []
    controller.sample(2, 0, 0, 1300)
    controller.sample(2, 1, 0, 1400)
    result = controller.sample(2, 1, 0, 1650)
    assert result["operations"][0]["channel_index"] == 8
    assert operations == [(8, True)]
    assert controller.sample(2, 1, 0, 3000)["operations"] == []


def test_off_throw_dispatches_false_and_maps_eighth_override():
    operations = []
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 4)
    for now in (500, 750):
        controller.sample(8, 0, 0, now)
    controller.sample(8, 0, 0b10000000, 1000)
    controller.sample(8, 0, 0b10000000, 1250)
    assert operations == [(31, False)]


def test_timeout_disables_dispatch_without_changing_relay_state():
    operations = []
    relay_state = {"A1": True, "D8": False}
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 1)
    expired = controller.sample(1, 0, 0, 5251)
    assert expired["active_bank"] == 0
    assert relay_state == {"A1": True, "D8": False}
    assert controller.sample(1, 1, 0, 5500)["operations"] == []
    assert operations == []


def test_valid_override_resets_timeout_but_blocked_activity_does_not():
    operations = []
    controller = infra.RCMBankController(lambda channel, value: operations.append((channel, value)))
    select(controller, 1)
    for now in (500, 750):
        controller.sample(1, 0, 0, now)
    controller.sample(1, 1, 0, 1000)
    controller.sample(1, 1, 0, 1250)
    result = controller.status(1250)
    assert result["timeout_remaining_ms"] == 5000
    controller.sample(1, 1, 0, 1500)
    result = controller.sample(1, 1, 0, 1800)
    assert result["operations"] == []
    assert result["timeout_remaining_ms"] == 4450
    assert operations == [(0, True)]


def test_millis_rollover_is_safe_for_debounce_and_timeout():
    controller = infra.RCMBankController(lambda *_: None)
    start = 0xFFFFFF00
    controller.sample(0, 0, 0, start)
    controller.sample(1, 0, 0, (start + 1) & 0xFFFFFFFF)
    selected_at = (start + 251) & 0xFFFFFFFF
    controller.sample(1, 0, 0, selected_at)
    assert controller.status(selected_at)["active_bank"] == 1
    assert controller.status((selected_at + 5000) & 0xFFFFFFFF)["active_bank"] == 1
    controller.sample(1, 0, 0, (selected_at + 5001) & 0xFFFFFFFF)
    assert controller.status((selected_at + 5001) & 0xFFFFFFFF)["active_bank"] == 0
