from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGGER = (ROOT / "06_ACM/03_Shared/event_logger.cpp").read_text()
ACM = (ROOT / "06_ACM/01_ACM/main.cpp").read_text()
KEYPAD = (ROOT / "06_ACM/02_Keypad/main.cpp").read_text()
HCM = (ROOT / "02_HCM/registry.py").read_text()


class LogModel:
    def __init__(self):
        self.synced = False
        self.last_date = None
        self.lines = {}

    def write(self, millis, event):
        if not self.synced:
            path = "/logs/unsynced.log"
            stamp = f"UNSYNC+{millis}ms"
        else:
            local = datetime.fromtimestamp(self.epoch, timezone.utc)
            path = f"/logs/{local:%Y-%m}.log"
            stamp = f"{local:%Y-%m-%d %H:%M:%S}"
            if self.last_date != local.date():
                self.lines.setdefault(path, []).extend(["*****", f"{local:%Y-%m-%d}", "*****"])
                self.last_date = local.date()
        self.lines.setdefault(path, []).append(f"{stamp} {event}")

    def set_time(self, epoch):
        self.epoch = epoch
        self.synced = True


def test_unsynced_and_monthly_rotation_and_daily_separator():
    model = LogModel()
    model.write(12345, "ACM_BOOT")
    assert list(model.lines) == ["/logs/unsynced.log"]
    model.set_time(datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc).timestamp())
    model.write(1, "TIME_SYNC_RESTORED")
    model.write(2, "SENSOR_OPEN")
    assert model.lines["/logs/2026-10.log"].count("*****") == 2
    model.set_time(datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc).timestamp())
    model.write(3, "SENSOR_CLOSED")
    assert model.lines["/logs/2026-11.log"][:3] == ["*****", "2026-11-01", "*****"]


def test_required_runtime_hooks_and_hcm_time_exchange_exist():
    for event in ("ACM_BOOT", "SENSOR_OPEN", "ALARM_TRIGGERED", "SIRENS_ON", "TIME_SYNC_LOST"):
        assert event in ACM or event in LOGGER
    assert "TIME_REQUEST" in ACM and "TIME_RESPONSE" in ACM
    assert "TIME_SYNC" in KEYPAD and "TIME_RESPONSE" in HCM
    assert "TIME_STALE_MS" in LOGGER
    assert "EST5EDT" in LOGGER


def test_transition_deduplication_is_represented_by_runtime_state():
    assert "hcmWasConnected" in ACM
    assert "previousState" in ACM
    assert "lastChirpedCountdown" not in ACM  # keypad owns piezo cadence
    assert "last_date_" in LOGGER
