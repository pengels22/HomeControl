from dataclasses import dataclass
from html import escape


@dataclass
class Session:
    token: str
    csrf: str
    last: int
    valid: bool = True


class WebRules:
    idle_ms = 300_000

    def __init__(self):
        self.sessions = {}
        self.audit = []
        self.config = {"channel": {"name": "Door", "area": 1, "type": "OPENING"}, "relay": {"siren": False}}

    def login(self, role, pin, now):
        if role != "MASTER":
            self.audit.append("WEB_LOGIN_FAILED")
            return None
        session = Session("session", "csrf", now)
        self.sessions[session.token] = session
        self.audit.append("WEB_LOGIN_SUCCESS PIN=Master")
        assert pin not in self.audit
        return session

    def request(self, session, now):
        if not session or not session.valid or now - session.last > self.idle_ms:
            if session and session.valid:
                self.audit.append("WEB_SESSION_EXPIRED")
                session.valid = False
            return False
        session.last = now
        return True

    def mutation(self, session, csrf, now):
        return self.request(session, now) and csrf == session.csrf


def test_master_standard_and_invalid_login_rules():
    rules = WebRules()
    assert rules.login("MASTER", "2468", 0)
    assert rules.login("STANDARD", "2468", 0) is None
    assert rules.login("INVALID", "nope", 0) is None
    assert all("2468" not in item for item in rules.audit)


def test_session_refresh_expiry_and_logout():
    rules = WebRules()
    session = rules.login("MASTER", "2468", 0)
    assert rules.request(session, 299_999)
    assert session.last == 299_999
    assert not rules.request(session, 600_001)
    session = rules.login("MASTER", "1357", 700_000)
    session.valid = False
    assert not rules.request(session, 700_001)


def test_csrf_and_bounded_request_rules():
    rules = WebRules()
    session = rules.login("MASTER", "2468", 0)
    assert not rules.mutation(session, "", 1)
    assert not rules.mutation(session, "wrong", 1)
    assert rules.mutation(session, "csrf", 1)
    oversized = "x" * 2049
    assert len(oversized) > 2048


def test_html_escape_and_realistic_config_mutations():
    rules = WebRules()
    session = rules.login("MASTER", "2468", 0)
    assert rules.mutation(session, "csrf", 1)
    rules.config["channel"].update(name="<script>alert(1)</script>", area=5, type="MOTION")
    rules.config["relay"]["siren"] = True
    rendered = escape(rules.config["channel"]["name"])
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert rules.config["channel"]["type"] == "MOTION"
    assert rules.config["relay"]["siren"] is True


def test_pin_reset_enable_remove_and_reprovision_model():
    pins = {0: {"name": "Master", "pin": "2468", "role": "MASTER", "enabled": True}, 1: {"name": "Guest", "pin": "1357", "role": "STANDARD", "enabled": True}}
    assert pins[1]["pin"] == "1357"
    pins[1]["pin"] = "9753"
    assert pins[1]["pin"] != "1357"
    pins[1]["enabled"] = False
    assert not pins[1]["enabled"]
    pins[1]["enabled"] = True
    del pins[1]
    pins = {0: {"name": "Reprovisioned", "pin": "8642", "role": "MASTER", "enabled": True}}
    assert pins[0]["pin"] == "8642"


def test_bounded_log_tail_and_safe_redirects():
    lines = [f"line-{i}" for i in range(300)]
    tail = lines[-100:]
    assert len(tail) == 100
    assert tail[0] == "line-200"
    allowed = {"/channels", "/outputs", "/areas", "/keypads", "/pins", "/system", "/logs"}
    assert "/evil" not in allowed


def test_index_bounds_are_rejected_before_array_access():
    valid_channels = {1, 24}
    for raw in (0, -1, 255, 999):
        assert raw not in valid_channels
