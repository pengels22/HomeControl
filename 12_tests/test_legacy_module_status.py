from importlib import import_module


legacy = import_module('01_HCM.legacy_module_status')


def test_fresh_install_policy_excludes_legacy_roles_without_erasing_history():
    assert legacy.role_available_for_new_install('PNL')
    assert legacy.role_available_for_new_install('RCM')
    assert legacy.role_available_for_new_install('LCM')
    assert not legacy.role_available_for_new_install('SIM')
    assert not legacy.role_available_for_new_install('RMC')
