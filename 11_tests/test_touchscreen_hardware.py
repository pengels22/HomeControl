from importlib import import_module
from pathlib import Path

import pytest


hardware = import_module("10_scripts.touchscreen_hardware")
interfaces = import_module("10_scripts.touchscreen_hardware.interfaces")
touch = import_module("10_scripts.touchscreen_hardware.ft6336_touch")
bridge = import_module("10_scripts.touchscreen_hardware.browser_bridge")
profiles = import_module("07_servises.common.hardware_profiles")

ROOT = Path(__file__).parents[1]


def test_validated_orange_pi_configs_match_travel_laser_reference():
    display = interfaces.DisplayConfig()
    touch_config = interfaces.TouchConfig()

    assert (display.width, display.height, display.rotation) == (480, 320, 90)
    assert (display.spi_device, display.spi_speed_hz) == ("/dev/spidev1.1", 10_000_000)
    assert (display.dc_gpio_chip, display.dc_gpio_line) == ("/dev/gpiochip1", 70)
    assert display.reset_gpio_line is None
    assert (touch_config.i2c_device, touch_config.i2c_address) == ("/dev/i2c-2", 0x38)
    assert (touch_config.reset_gpio_chip, touch_config.reset_gpio_line) == ("/dev/gpiochip1", 69)


def test_ft6336_rotation_transform_is_stable():
    driver = touch.FT6336Touch(interfaces.TouchConfig(rotation=90), poll_interval=0)
    assert driver._transform(0, 0) == (0, 319)
    assert driver._transform(480, 320) == (320, 0)


def test_simulated_service_never_opens_hardware_nodes():
    service = hardware.create_service("SIM", mode="simulated")
    assert service.mode == "simulated"
    assert service.create_display() is None
    assert service.create_touch() is None


def test_jetson_adapter_is_separate_from_orange_pi_profile():
    adapter = import_module("10_scripts.touchscreen_hardware.jetson_adapter")
    config = adapter.create_jetson_adapter_config()
    assert config.spi_device == "/dev/spidev0.0"
    assert config.i2c_device == "/dev/i2c-0"
    assert config.spi_device != interfaces.DisplayConfig().spi_device


def test_kiosk_bridge_preserves_role_and_display_size():
    config = bridge.BrowserBridgeConfig(role="lcm")
    command = config.command()
    assert "--kiosk" in command
    assert "--window-size=480,320" in command
    assert command[-1] == "http://127.0.0.1:8765/?role=LCM"


@pytest.mark.parametrize("module_type", ["RCM", "LCM", "SIM"])
def test_orange_pi_manifests_use_touchscreen_mapping_and_keep_outputs_disabled(module_type):
    profile = profiles.load_profile(profiles.profile_path(ROOT, module_type), module_type)
    header = profile.data["processor_header"]
    assert profile.physical_output_enabled is False
    assert header["11"]["function"] == "LCD_DC"
    assert header["13"]["function"] == "TOUCH_RESET"
    assert header["24"]["function"] == "SPI1_CS1_LCD"
    assert profile.data["buses"]["spi"]["display"]["device"] == "/dev/spidev1.1"
    assert profile.data["buses"]["i2c"]["touch"]["device"] == "/dev/i2c-2"


def test_sim_leds_use_non_display_header_pins():
    profile = profiles.load_profile(profiles.profile_path(ROOT, "SIM"), "SIM")
    header = profile.data["processor_header"]
    assert header["15"]["function"] == "LINK_LED"
    assert header["16"]["function"] == "STATUS_LED"
    assert header["22"]["function"] == "FAULT_LED"


def test_hcm_jetson_manifest_is_unchanged_by_orange_pi_profile():
    profile = profiles.load_profile(profiles.profile_path(ROOT, "HCM"), "HCM")
    header = profile.data["processor_header"]
    assert header["22"]["function"] == "LCD_DC"
    assert header["24"]["function"] == "SPI0_CS0"


def test_overlay_is_manual_spi1_cs1_overlay():
    text = (ROOT / "10_scripts/touchscreen_hardware/overlays/spi1-cs1-pins.dts").read_text()
    assert "target = <&spi1>;" in text
    assert "&spi1_cs1_pin" in text
    assert "status = \"okay\";" in text
