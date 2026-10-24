from pathlib import Path

from importlib import import_module


ROOT = Path(__file__).resolve().parents[1]


def test_obsolete_sim_tree_is_absent():
    assert not (ROOT / "02_SIM").exists()
    assert not (ROOT / "07_config" / "02_SIM").exists()
    assert not list((ROOT / "02_SIM").glob("**/*"))


def test_active_module_registration_excludes_sim():
    registry = import_module("02_HCM.registry")
    roles = import_module("02_HCM.role_switching")
    assert "SIM" not in registry.MODULE_TYPES
    assert "SIM" not in roles.ALLOWED_ROLES
    assert "SIM" not in roles.REGISTERED_MODULE_ROLES


def test_fresh_install_inventory_excludes_sim():
    inventory = import_module("07_config.10_Common.inventory")
    manifest = import_module("07_config.10_Common.manifest")
    assert "SIM" not in manifest.DEVICE_TYPES
    assert "SIM" not in manifest.LINUX_DEVICE_TYPES
    assert inventory.package_for_device("PNL") == "05_PNL"
    try:
        inventory.package_for_device("SIM")
    except inventory.InventoryError:
        pass
    else:
        raise AssertionError("SIM must not be provisionable")


def test_pnl_package_has_no_sim_import_dependency():
    source = (ROOT / "05_PNL").glob("**/*.py")
    assert all("02_SIM" not in path.read_text(errors="ignore") for path in source)
