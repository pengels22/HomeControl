from pathlib import Path


ROOT = Path(__file__).parents[1]


def source(path):
    return (ROOT / path).read_text()


def test_embedded_web_server_is_in_acm_firmware_and_non_secret_by_design():
    header = source("06_ACM/03_Shared/web_admin.h")
    implementation = source("06_ACM/03_Shared/web_admin.cpp")
    main = source("06_ACM/01_ACM/main.cpp")
    assert "PORT = 80" in header
    assert "SESSION_IDLE_MS = 300000UL" in header
    assert "server_(PORT)" in header
    assert "webAdmin.tick(now)" in main
    assert "PinAuthResult auth=pins_->authenticate(pin)" in implementation
    assert "auth.role==PinRole::MASTER" in implementation
    assert "WEB_LOGIN_FAILED" in implementation
    assert "WEB_SESSION_EXPIRED" in implementation
    assert "ACMSESSION" in implementation
    assert "SameSite=Strict" in implementation
    assert "type='password'" in implementation


def test_web_routes_and_mutations_cover_v1_administration_surface():
    implementation = source("06_ACM/03_Shared/web_admin.cpp")
    for route in ("channels", "outputs", "areas", "keypads", "pins", "system", "logs", "logout"):
        assert f'"/{route}"' in implementation
    for action in ("channel", "relay", "area_add", "area_rename", "keypad_add", "keypad_remove", "pin_add", "pin_enable"):
        assert action in implementation
    assert "requireCsrf" in implementation
    assert "htmlEscape" in implementation
    assert "recentLines(100)" in implementation


def test_pin_admin_mutations_use_master_reauthentication_and_audit_without_secrets():
    pin_store = source("06_ACM/03_Shared/pin_store.cpp")
    web = source("06_ACM/03_Shared/web_admin.cpp")
    for method in ("addPin", "resetPin", "renamePin", "setEnabled"):
        assert method in pin_store
    for event in ("PIN_ADDED", "PIN_ENABLED", "PIN_DISABLED"):
        assert event in web
    assert "PIN=" in web
    assert "hash" not in web.lower()
    assert "salt" not in web.lower()
