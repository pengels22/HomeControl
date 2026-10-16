"""Capture touchscreen preview pages with Playwright when installed.

Usage: python 10_scripts/screenshot_touchscreen.py --base-url http://127.0.0.1:8765
The preview server must already be running. This script never connects to HCM.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROLES = {
    "RCM": {"home": [], "status": ["status"], "relays": ["relays"], "network": ["network"], "settings": ["settings"]},
    "LCM": {"home": [], "status": ["status"], "lights": ["lights"], "dimmers": ["lights", "dimmers"], "non-dimmers": ["lights", "non-dimmers"], "network": ["network"], "settings": ["settings"]},
    "SIM": {"home": [], "status": ["status"], "rmc-data": ["rmc-data"], "network": ["network"], "settings": ["settings"]},
    "HCM": {"home": [], "status": ["status"], "sensors": ["sensors"], "network": ["network"], "settings": ["settings"]},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="tmp/touchscreen-screenshots")
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Install the optional Playwright browser tooling to capture screenshots") from exc
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        for role, pages in ROLES.items():
            for name, path in pages.items():
                page.goto(f"{args.base_url}/?role={role}")
                for step in path:
                    page.locator(f"[data-page='{step}']").first.click()
                page.screenshot(path=str(output / f"{role.lower()}-{name}.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
