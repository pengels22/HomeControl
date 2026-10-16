"""Kiosk-browser launch contract for the shared touchscreen UI.

The browser remains the shared UI source of truth.  This module only builds a
deterministic commissioning command; it intentionally does not launch a
browser or access hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class BrowserBridgeConfig:
    base_url: str = "http://127.0.0.1:8765/"
    role: str = "RCM"
    width: int = 480
    height: int = 320
    browser_binary: str = "chromium"

    def url(self) -> str:
        parts = urlsplit(self.base_url)
        query = dict()
        if parts.query:
            query.update(item.split("=", 1) for item in parts.query.split("&") if "=" in item)
        query["role"] = self.role.upper()
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))

    def command(self) -> list[str]:
        return [
            self.browser_binary,
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            f"--window-size={self.width},{self.height}",
            self.url(),
        ]
