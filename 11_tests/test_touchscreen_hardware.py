import asyncio
from importlib import import_module
from pathlib import Path

import pytest


hardware = import_module("10_scripts.touchscreen_hardware")
interfaces = import_module("10_scripts.touchscreen_hardware.interfaces")
touch = import_module("10_scripts.touchscreen_hardware.ft6336_touch")
bridge = import_module("10_scripts.touchscreen_hardware.browser_bridge")
input_bridge = import_module("10_scripts.touchscreen_hardware.input_bridge")
renderer = import_module("10_scripts.touchscreen_hardware.browser_renderer")
profiles = import_module("07_servises.common.hardware_profiles")
bench = import_module("10_scripts.travel_laser_bench")
native = import_module("10_scripts.touchscreen_native")

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


def test_native_production_api_requires_authenticated_hcm_and_logical_bindings(monkeypatch):
    monkeypatch.delenv("HOMECONTROL_HCM_API_URL", raising=False)
    monkeypatch.delenv("HOMECONTROL_HCM_TOKEN", raising=False)
    monkeypatch.delenv("HOMECONTROL_TOUCHSCREEN_LOGICAL_MAP", raising=False)
    with pytest.raises(RuntimeError, match="requires HCM URL"):
        native.api_client_for_mode("production")

    monkeypatch.setenv("HOMECONTROL_HCM_API_URL", "https://hcm.test/api/v1")
    monkeypatch.setenv("HOMECONTROL_HCM_TOKEN", "test-token")
    monkeypatch.setenv("HOMECONTROL_TOUCHSCREEN_MODULE_ID", "RCM-01")
    monkeypatch.setenv("HOMECONTROL_TOUCHSCREEN_LOGICAL_MAP", '{"RCM:A1":"relay-a1"}')
    client = native.api_client_for_mode("production")
    assert client.token == "test-token"
    assert client.module_identifier == "RCM-01"
    assert client.logical_map == {"RCM:A1": "relay-a1"}


def test_native_renderer_draws_shared_frame_without_browser():
    class Display:
        width = 480
        height = 320

        async def draw_rgb565(self, x, y, width, height, data):
            self.frame = (x, y, width, height, data)

    display = Display()
    ui = native.NativeUI("SIM", display)
    ui.state = {
        "module": {"name": "SIM-01", "role": "SIM", "simulation": True, "physical_outputs_enabled": False},
        "health": {"status": "SIMULATED"},
        "settings": {"inactivity_seconds": 10, "hardware_profile": "SIMULATED"},
    }
    asyncio.run(ui.draw())
    assert display.frame[:4] == (0, 0, 480, 320)
    assert len(display.frame[4]) == 480 * 320 * 2


def test_native_rcm_bank_selection_filters_eight_channels_and_preserves_mapping():
    class Display:
        width = 480
        height = 320

        async def draw_rgb565(self, *args):
            pass

    class Api:
        def __init__(self):
            self.calls = []

        def request(self, path, payload=None):
            previous_command = next((item[1] for item in reversed(self.calls) if item[1] is not None), None)
            self.calls.append((path, payload))
            return {"ok": True, "bank": payload.get("bank", 0)} if payload else {
                "module": {"name": "RCM-01"}, "health": {"status": "SIMULATED"},
                "settings": {"inactivity_seconds": 10},
                    "bank_selector": {"effective_bank": previous_command.get("bank", 0) if previous_command else 0},
                "relays": [{"channel": f"{bank}{number}", "position": index, "name": f"Relay {index}", "on": False, "lockout": False}
                            for index, (bank, number) in enumerate(((b, n) for b in "ABCD" for n in range(1, 9)), 1)],
            }

    api = Api()
    ui = native.NativeUI("RCM", Display(), api)
    ui.page = "relays"
    ui.state = {"settings": {"inactivity_seconds": 10}, "bank_selector": {"effective_bank": 0}, "relays": [
        {"channel": f"{bank}{number}", "position": index, "name": f"Relay {index}", "on": False, "lockout": False}
        for index, (bank, number) in enumerate(((b, n) for b in "ABCD" for n in range(1, 9)), 1)
    ]}
    asyncio.run(ui._tap(10 + 2 * 117 + 10, 110))
    assert ui.bank == 2
    command = next(payload for _, payload in api.calls if payload and payload.get("kind") == "bank_select")
    assert command["bank"] == 2
    assert [item["channel"] for item in ui.state["relays"] if (item["position"] - 1) // 8 == ui.bank] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]


def test_native_lockout_does_not_send_relay_command_and_timeout_is_editable_only():
    class Display:
        width = 480
        height = 320

        async def draw_rgb565(self, *args):
            pass

    class Api:
        def __init__(self): self.calls = []
        def request(self, path, payload=None):
            self.calls.append((path, payload))
            if payload and payload["kind"] == "setting": return {"ok": True}
            return {"settings": {"inactivity_seconds": 10}, "bank_selector": {"effective_bank": 0}}

    api = Api(); ui = native.NativeUI("RCM", Display(), api)
    ui.page = "relays"; ui.state = {"settings": {"inactivity_seconds": 10}, "relays": [{"channel": "A1", "position": 1, "name": "Locked", "on": False, "lockout": True}]}
    asyncio.run(ui._tap(440, 145))
    assert not any(call[1] and call[1].get("kind") == "relay" for call in api.calls)
    ui.page = "settings"
    asyncio.run(ui._tap(310, 120))
    assert next(payload for _, payload in api.calls if payload and payload.get("kind") == "setting") == {"kind": "setting", "setting": "screen_timeout", "value": 11, "role": "RCM"}


def test_native_back_button_returns_from_any_subpage_to_home():
    class Display:
        width = 480
        height = 320

        async def draw_rgb565(self, *args):
            pass

    ui = native.NativeUI("SIM", Display())
    ui.page = "settings"
    event = interfaces.TouchEvent("down", (interfaces.TouchPoint(0, 40, 72),))
    asyncio.run(ui.touch(event))
    assert ui.page == "home"


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


class RecordingSink:
    def __init__(self):
        self.events = []

    def open(self):
        self.events.append(("open",))

    def press(self, point):
        self.events.append(("press", point.x, point.y))

    def move(self, point):
        self.events.append(("move", point.x, point.y))

    def release(self, point=None):
        self.events.append(("release", None if point is None else (point.x, point.y)))

    def close(self):
        self.events.append(("close",))


def test_touch_bridge_forwards_press_drag_and_release_for_browser_gestures():
    sink = RecordingSink()
    event_bridge = input_bridge.TouchEventBridge(sink)
    point = interfaces.TouchPoint(0, 120, 240)

    assert event_bridge.handle(interfaces.TouchEvent("down", (point,)))
    assert event_bridge.handle(interfaces.TouchEvent("move", (interfaces.TouchPoint(0, 120, 120),)))
    assert event_bridge.handle(interfaces.TouchEvent("up", ()))
    assert sink.events == [
        ("press", 120, 240),
        ("move", 120, 120),
        ("release", (120, 120)),
    ]
    assert event_bridge.active_id is None


def test_touch_bridge_ignores_stale_contacts_and_cancels_active_contact():
    sink = RecordingSink()
    event_bridge = input_bridge.TouchEventBridge(sink)
    event_bridge.handle(interfaces.TouchEvent("down", (interfaces.TouchPoint(7, 10, 20),)))
    assert not event_bridge.handle(interfaces.TouchEvent("move", (interfaces.TouchPoint(8, 11, 21),)))
    event_bridge.cancel()
    assert sink.events == [("press", 10, 20), ("release", (10, 20))]


class FakeTouch:
    def __init__(self):
        self.events = [
            interfaces.TouchEvent("down", (interfaces.TouchPoint(0, 60, 80),)),
            interfaces.TouchEvent("move", (interfaces.TouchPoint(0, 60, 160),)),
            interfaces.TouchEvent("up", ()),
        ]
        self.initialized = False
        self.closed = False

    async def initialize(self):
        self.initialized = True

    async def read_event(self):
        if self.events:
            return self.events.pop(0)
        await asyncio.sleep(0)
        return None

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_run_touch_input_exercises_consumer_lifecycle_and_browser_sink():
    sink = RecordingSink()
    touch = FakeTouch()
    stop = asyncio.Event()

    async def stop_after_release():
        while len(sink.events) < 4:
            await asyncio.sleep(0)
        stop.set()

    await asyncio.gather(input_bridge.run_touch_input(touch, sink, stop), stop_after_release())
    assert touch.initialized is True
    assert touch.closed is True
    assert sink.events == [
        ("open",),
        ("press", 60, 80),
        ("move", 60, 160),
        ("release", (60, 160)),
        ("close",),
    ]


@pytest.mark.asyncio
async def test_touch_input_closes_sink_when_touch_initialization_fails():
    class FailingTouch:
        def __init__(self):
            self.closed = False

        async def initialize(self):
            raise OSError("I2C unavailable")

        async def close(self):
            self.closed = True

    sink = RecordingSink()
    touch = FailingTouch()
    with pytest.raises(OSError, match="I2C unavailable"):
        await input_bridge.run_touch_input(touch, sink, asyncio.Event())
    assert sink.events == [("open",), ("close",)]
    assert touch.closed is True


def test_rgb565_conversion_uses_big_endian_wire_order():
    assert renderer.rgb888_to_rgb565(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])) == bytes([
        0xF8, 0x00, 0x07, 0xE0, 0x00, 0x1F,
    ])


def test_dirty_update_sends_full_frame_then_only_changed_rectangle():
    first = bytes([0, 0, 0] * 4)
    second = bytearray(first)
    second[3:6] = bytes([255, 0, 0])

    full = renderer._dirty_update(None, first, 2, 2)
    partial = renderer._dirty_update(first, bytes(second), 2, 2)
    unchanged = renderer._dirty_update(bytes(second), bytes(second), 2, 2)

    assert (full.x, full.y, full.width, full.height) == (0, 0, 2, 2)
    assert (partial.x, partial.y, partial.width, partial.height) == (1, 0, 1, 1)
    assert unchanged is None


def test_cdp_touch_sink_uses_same_touch_lifecycle_as_uinput_sink():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def command(self, method, params=None):
            self.calls.append((method, params))

    client = FakeClient()
    sink = input_bridge.CdpTouchSink(client)
    point = interfaces.TouchPoint(0, 10, 20)
    sink.open()
    sink.press(point)
    sink.move(interfaces.TouchPoint(0, 10, 40))
    sink.release(point)

    assert [call[0] for call in client.calls] == [
        "Input.setIgnoreInputEvents",
        "Input.dispatchTouchEvent",
        "Input.dispatchTouchEvent",
        "Input.dispatchTouchEvent",
    ]
    assert client.calls[1][1]["type"] == "touchStart"
    assert client.calls[2][1]["type"] == "touchMove"
    assert client.calls[3][1]["type"] == "touchEnd"


def test_cdp_touch_sink_scales_physical_coordinates_to_virtual_viewport():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def command(self, method, params=None):
            self.calls.append((method, params))

    client = FakeClient()
    sink = input_bridge.CdpTouchSink(client, coordinate_scale=2.0)
    sink.press(interfaces.TouchPoint(0, 12, 18))

    point = client.calls[-1][1]["touchPoints"][0]
    assert (point["x"], point["y"]) == (24, 36)


def test_browser_renderer_config_is_exactly_480x320_and_headless():
    config = renderer.BrowserRendererConfig()
    command = config.command()
    assert (config.width, config.height) == (480, 320)
    assert (config.viewport_width, config.viewport_height) == (960, 640)
    assert "--headless=new" in command
    assert "--no-sandbox" in command
    assert "--remote-allow-origins=*" in command
    assert "--remote-debugging-port=9222" in command
    assert command[-1].startswith("http://127.0.0.1:8765/")


def test_restore_commands_only_touch_test_resources_and_original_service_state():
    commands = bench.restore_commands({"service_active": "active", "service_enabled": "enabled"})
    joined = "; ".join(commands)
    assert "travel-laser-ui.service" in joined
    assert "/tmp/homecontrol-touchscreen-test.pids" in joined
    assert "pkill -TERM -P" in joined
    assert "gpio" not in joined.lower()
    assert "relay" not in joined.lower()
    assert any("systemctl start travel-laser-ui.service" in command for command in commands)
    assert any("systemctl enable travel-laser-ui.service" in command for command in commands)


def test_preflight_reports_ssh_or_remote_check_failures():
    results = {"identity": {"returncode": 255}, "manual": {"returncode": 0}}
    assert not bench.preflight_ok(results)
    assert bench.preflight_ok({"identity": {"returncode": 0}, "manual": {"returncode": 0}})


def test_bench_handover_requires_renderer_dependencies_but_not_uinput_for_cdp():
    missing = {"dependencies": {"stdout": "spidev=missing\ngpiod=missing\nsmbus2=missing\n"}}
    ready = {"dependencies": {"stdout": "spidev=available\ngpiod=available\nsmbus2=available\nevdev=missing\n"}}
    assert not bench.dependencies_ready(missing)
    assert bench.dependencies_ready(ready)


@pytest.mark.asyncio
async def test_browser_renderer_start_capture_and_shutdown_are_reversible(tmp_path, monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            return 0

    class FakeClient:
        def __init__(self, url):
            self.url = url
            self.connected = False
            self.closed = False

        def connect(self):
            self.connected = True

        def command(self, method, params=None):
            if method == "Page.captureScreenshot":
                return {"data": "ignored"}
            return {}

        def close(self):
            self.closed = True

    process = FakeProcess()
    client = None

    def make_process(*args, **kwargs):
        return process

    def make_client(url):
        nonlocal client
        client = FakeClient(url)
        return client

    display = type("Display", (), {"draw_rgb565": lambda self, *args: asyncio.sleep(0)})()
    config = renderer.BrowserRendererConfig(width=2, height=1, user_data_dir=tmp_path / "browser")
    browser = renderer.BrowserRenderer(display, config, make_process, make_client)
    monkeypatch.setattr(browser, "_wait_for_page", lambda: {"webSocketDebuggerUrl": "ws://fake"})
    monkeypatch.setattr(renderer, "_decode_rgb", lambda encoded: bytes([255, 0, 0, 0, 0, 0]))
    monkeypatch.setattr(renderer, "_resize_rgb", lambda rgb, *_sizes: rgb)

    await browser.start()
    assert client.connected is True
    update = await browser.capture_update()
    assert (update.width, update.height) == (2, 1)
    await browser.stop()
    assert client.closed is True
    assert process.terminated is True


@pytest.mark.asyncio
async def test_browser_renderer_stops_resources_after_capture_failure():
    class FakeProcess:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    class FailingClient:
        def __init__(self):
            self.closed = False

        def command(self, method, params=None):
            raise RuntimeError("renderer disconnected")

        def close(self):
            self.closed = True

    browser = renderer.BrowserRenderer(type("Display", (), {})())
    browser.process = FakeProcess()
    browser.client = FailingClient()
    with pytest.raises(RuntimeError, match="renderer disconnected"):
        await browser.run()
    assert browser.process is None
    assert browser.client is None
