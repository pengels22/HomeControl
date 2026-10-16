#!/usr/bin/env python3
"""Native HomeControl touchscreen renderer.

This keeps the HomeControl API as the authority while rendering the shared
touchscreen UI directly to the validated ST7796U RGB565 display.  It avoids a
browser, screenshot capture, and a compositor in the control path.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import signal
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # The simulated test environment does not need Pillow.
    Image = ImageDraw = ImageFont = None

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("homecontrol.native_touchscreen")
FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
)

BLACK, WHITE = 0x0000, 0xFFFF
PANEL, CARD, LINE = 0x10A3, 0x1968, 0x05DF
CYAN, MUTED, GOOD, WARN, BAD = 0x67DF, 0x6D9B, 0x37EA, 0xFD20, 0xF2EA

GLYPHS = {
    " ": (".....",) * 7,
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ".": (".....",) * 5 + ("..#..", "..#.."),
    ":": (".....", "..#..", "..#..", ".....", "..#..", "..#..", "....."),
    "/": ("....#", "...#.", "..#..", ".#...", "#....", "#....", "....."),
    "%": ("##..#", "##.#.", "...#.", "..#..", ".#...", ".#.##", "#..##"),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
}
for letter, rows in {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", ".#.#.", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
}.items():
    GLYPHS[letter] = rows
for number, rows in {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "#....", "####.", "....#", "....#", "####."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
}.items():
    GLYPHS[number] = rows


class Frame:
    def __init__(self, width: int = 480, height: int = 320, color: int = BLACK):
        self.width, self.height = width, height
        self.data = bytearray(width * height * 2)
        self._font_cache: dict[int, Any] = {}
        self.fill(color)

    def fill(self, color: int) -> None:
        self.data[:] = color.to_bytes(2, "big") * (self.width * self.height)

    def rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        self.fill_rect(x, y, w, 1, color); self.fill_rect(x, y + h - 1, w, 1, color)
        self.fill_rect(x, y, 1, h, color); self.fill_rect(x + w - 1, y, 1, h, color)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        if w <= 0 or h <= 0: return
        pixel = color.to_bytes(2, "big")
        for row in range(max(0, y), min(self.height, y + h)):
            left, right = max(0, x), min(self.width, x + w)
            start, end = (row * self.width + left) * 2, (row * self.width + right) * 2
            self.data[start:end] = pixel * ((end - start) // 2)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int) -> None:
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.fill_rect(x0, y0, 1, 1, color)
            if x0 == x1 and y0 == y1:
                return
            double = 2 * error
            if double >= dy:
                error += dy; x0 += sx
            if double <= dx:
                error += dx; y0 += sy

    def circle(self, cx: int, cy: int, radius: int, color: int) -> None:
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                    self.fill_rect(x, y, 1, 1, color)

    def rounded_rect(self, x: int, y: int, w: int, h: int, radius: int, color: int, outline: int | None = None) -> None:
        radius = max(1, min(radius, w // 2, h // 2))
        self.fill_rect(x + radius, y, w - 2 * radius, h, color)
        self.fill_rect(x, y + radius, w, h - 2 * radius, color)
        for cx, cy in ((x + radius, y + radius), (x + w - radius - 1, y + radius),
                       (x + radius, y + h - radius - 1), (x + w - radius - 1, y + h - radius - 1)):
            self.circle(cx, cy, radius, color)
        if outline is not None:
            self.rect(x + radius, y, w - 2 * radius, 1, outline)
            self.rect(x + radius, y + h - 1, w - 2 * radius, 1, outline)
            self.rect(x, y + radius, 1, h - 2 * radius, outline)
            self.rect(x + w - 1, y + radius, 1, h - 2 * radius, outline)

    def pill(self, x: int, y: int, w: int, h: int, color: int) -> None:
        radius = h // 2
        self.fill_rect(x + radius, y, max(0, w - 2 * radius), h, color)
        self.circle(x + radius, y + radius, radius, color)
        self.circle(x + w - radius - 1, y + radius, radius, color)

    def text(self, x: int, y: int, value: Any, color: int = WHITE, scale: int = 1, limit: int = 50) -> None:
        value = str(value)[:limit].upper()
        if Image is not None and ImageDraw is not None and ImageFont is not None:
            font = self._font_cache.get(scale)
            if font is None:
                font_path = next((path for path in FONT_PATHS if Path(path).exists()), None)
                if font_path:
                    font = ImageFont.truetype(font_path, max(11, scale * 9))
                    self._font_cache[scale] = font
            if font is not None:
                self._smooth_text(x, y, value, color, font)
                return
        cursor = x
        for char in value:
            glyph = GLYPHS.get(char, GLYPHS["?"])
            for row, pixels in enumerate(glyph):
                for col, pixel in enumerate(pixels):
                    if pixel == "#": self.fill_rect(cursor + col * scale, y + row * scale, scale, scale, color)
            cursor += 6 * scale

    def _smooth_text(self, x: int, y: int, value: str, color: int, font: Any) -> None:
        if not value:
            return
        probe = Image.new("L", (1, 1), 0)
        probe_draw = ImageDraw.Draw(probe)
        left, top, right, bottom = probe_draw.textbbox((0, 0), value, font=font)
        mask = Image.new("L", (right - left + 2, bottom - top + 2), 0)
        ImageDraw.Draw(mask).text((-left + 1, -top + 1), value, font=font, fill=255)
        red, green, blue = ((color >> 11) & 0x1F) * 255 // 31, ((color >> 5) & 0x3F) * 255 // 63, (color & 0x1F) * 255 // 31
        for row in range(mask.height):
            target_y = y + row
            if not 0 <= target_y < self.height:
                continue
            for column in range(mask.width):
                target_x = x + column
                if not 0 <= target_x < self.width:
                    continue
                alpha = mask.getpixel((column, row))
                if not alpha:
                    continue
                offset = (target_y * self.width + target_x) * 2
                existing = int.from_bytes(self.data[offset:offset + 2], "big")
                old_red, old_green, old_blue = ((existing >> 11) & 0x1F) * 255 // 31, ((existing >> 5) & 0x3F) * 255 // 63, (existing & 0x1F) * 255 // 31
                blend = alpha / 255
                mixed = ((round(old_red * (1 - blend) + red * blend) * 31 // 255) << 11) | ((round(old_green * (1 - blend) + green * blend) * 63 // 255) << 5) | (round(old_blue * (1 - blend) + blue * blend) * 31 // 255)
                self.data[offset:offset + 2] = mixed.to_bytes(2, "big")


def inside(x: int, y: int, box: tuple[int, int, int, int]) -> bool:
    bx, by, bw, bh = box
    return bx <= x < bx + bw and by <= y < by + bh


@dataclass
class ApiClient:
    base_url: str = "http://127.0.0.1:8765"

    def request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.loads(response.read().decode())


class NativeUI:
    def __init__(self, role: str, display, api: ApiClient | None = None):
        self.role, self.display, self.api = role.upper(), display, api or ApiClient()
        self.width, self.height = display.width, display.height
        self.page, self.bank, self.scroll = "home", 0, 0
        self.state: dict[str, Any] = {}
        self.drag_channel: str | None = None
        self.drag_percent = 0
        self.pending: set[str] = set()
        self.last_touch = time.monotonic()
        self.timeout_seconds = 10

    async def refresh(self) -> None:
        try:
            self.state = await asyncio.to_thread(self.api.request, f"/api/touchscreen/state?role={self.role}")
            self.timeout_seconds = max(1, min(300, int(self.state.get("settings", {}).get("inactivity_seconds", 10))))
            selector = self.state.get("bank_selector", {})
            self.bank = int(selector.get("effective_bank", self.bank))
        except Exception as exc:
            LOGGER.warning("native state refresh failed: %s", exc)

    async def command(self, payload: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self.api.request, "/api/touchscreen/command", {**payload, "role": self.role})
            await self.refresh()
        except Exception as exc:
            LOGGER.warning("native command failed: %s", exc)
        await self.draw()

    async def draw(self) -> None:
        frame = Frame(self.width, self.height)
        self._header(frame)
        if self.page == "home": self._home(frame)
        elif self.page == "status": self._status(frame)
        elif self.page == "relays": self._relays(frame)
        elif self.page == "lights": self._lights(frame)
        elif self.page == "dimmers": self._dimmers(frame)
        elif self.page == "non-dimmers": self._relays(frame, title="NON-DIMMERS", items=self.state.get("relays", [])[:8])
        elif self.page == "network": self._network(frame)
        elif self.page == "settings": self._settings(frame)
        elif self.page == "rmc-data": self._rooms(frame)
        else: self._status(frame)
        await self.display.draw_rgb565(0, 0, self.width, self.height, bytes(frame.data))

    def _header(self, frame: Frame) -> None:
        frame.fill_rect(0, 0, self.width, self.height, BLACK)
        frame.rounded_rect(8, 8, self.width - 16, self.height - 16, 14, BLACK, LINE)
        frame.text(18, 16, "HOMECONTROL", WHITE, 2)
        frame.text(380, 18, time.strftime("%I:%M"), CYAN, 1)
        if self.page != "home":
            frame.rounded_rect(12, 45, 74, 28, 7, PANEL, LINE); frame.text(26, 55, "BACK", WHITE, 1)

    def _home(self, frame: Frame) -> None:
        module = self.state.get("module", {}); health = self.state.get("health", {})
        frame.rounded_rect(16, 50, 448, 98, 14, CARD, LINE)
        name = str(module.get("name", "MODULE")); frame.text(max(20, (480 - len(name) * 18) // 2), 68, name, WHITE, 3)
        status = str(health.get("status", "UNAVAILABLE")); status_color = GOOD if status == "SIMULATED" else WARN
        frame.circle(176, 119, 7, status_color); frame.text(192, 113, status, status_color, 2)
        labels = ["STATUS", "RELAYS" if self.role == "RCM" else "LIGHTS", "NETWORK", "SETTINGS"]
        pages = ["status", "relays" if self.role == "RCM" else ("lights" if self.role == "LCM" else "rmc-data"), "network", "settings"]
        for i, (label, page) in enumerate(zip(labels, pages, strict=True)):
            x, y = 16 + (i % 2) * 232, 154 + (i // 2) * 68
            frame.rounded_rect(x, y, 216, 58, 12, CARD, LINE)
            self._home_icon(frame, x + 108, y + 17, i)
            frame.text(x + max(20, (216 - len(label) * 12) // 2), y + 36, label, WHITE, 2)
        frame.text(134, 294, "RETURN HOME AFTER 10 SEC", MUTED, 1)

    def _home_icon(self, frame: Frame, cx: int, cy: int, index: int) -> None:
        if index == 0:
            frame.circle(cx, cy, 10, CYAN); frame.circle(cx, cy, 6, CARD)
        elif index == 1:
            frame.line(cx, cy - 12, cx + 12, cy, CYAN); frame.line(cx + 12, cy, cx, cy + 12, CYAN)
            frame.line(cx, cy + 12, cx - 12, cy, CYAN); frame.line(cx - 12, cy, cx, cy - 12, CYAN)
            frame.fill_rect(cx - 4, cy - 4, 9, 9, CYAN)
        elif index == 2:
            frame.line(cx - 13, cy - 4, cx - 2, cy + 2, CYAN); frame.line(cx - 2, cy + 2, cx - 2, cy - 7, CYAN)
            frame.line(cx - 2, cy - 7, cx + 13, cy + 5, CYAN); frame.line(cx + 13, cy + 5, cx + 13, cy - 4, CYAN)
        else:
            frame.circle(cx, cy, 8, CYAN); frame.circle(cx, cy, 4, CARD)
            for dx, dy in ((0, -13), (0, 9), (-13, 0), (9, 0), (-9, -9), (9, 9), (-9, 9), (9, -9)):
                frame.fill_rect(cx + dx - 2, cy + dy - 2, 5, 5, CYAN)

    def _status(self, frame: Frame) -> None:
        module, health, settings = self.state.get("module", {}), self.state.get("health", {}), self.state.get("settings", {})
        self._page_heading(frame, "STATUS")
        frame.rounded_rect(16, 82, 448, 218, 14, CARD, LINE)
        status = str(health.get("status", "UNAVAILABLE")); status_color = GOOD if status == "SIMULATED" else WARN
        frame.circle(38, 104, 6, status_color); frame.text(52, 98, module.get("name", "MODULE"), WHITE, 2); frame.text(330, 101, status, status_color, 1)
        rows = [("ROLE", module.get("role", "UNKNOWN")), ("IDENTITY", module.get("device_id", "UNKNOWN")), ("HEARTBEAT", health.get("heartbeat", "UNKNOWN")), ("SIMULATION", module.get("simulation", "UNKNOWN")), ("OUTPUTS", module.get("physical_outputs_enabled", "UNKNOWN")), ("PROFILE", settings.get("hardware_profile", "UNKNOWN"))]
        for i, (label, value) in enumerate(rows):
            y = 132 + i * 25; frame.text(30, y, label, MUTED); frame.text(170, y, str(value), WHITE)
            if i < len(rows) - 1: frame.fill_rect(28, y + 18, 424, 1, PANEL)

    def _page_heading(self, frame: Frame, title: str) -> None:
        frame.text(100, 51, title, CYAN, 2)

    def _relays(self, frame: Frame, title: str = "RELAYS", items: list[dict[str, Any]] | None = None) -> None:
        self._page_heading(frame, title); items = items if items is not None else self.state.get("relays", [])
        if title == "RELAYS" and self.role == "RCM":
            for index, label in enumerate(("1-8", "9-16", "17-24", "25-32")):
                x = 10 + index * 117; color = CYAN if index == self.bank else CARD
                frame.rounded_rect(x, 82, 110, 27, 7, color, LINE); frame.text(x + 29, 91, label, BLACK if index == self.bank else WHITE)
            items = [item for item in items if (int(item.get("position", 1)) - 1) // 8 == self.bank]
            start = 118
        else: start = 82
        for index, item in enumerate(items[:8]):
            y = start + index * 22
            frame.rounded_rect(12, y, 456, 19, 6, CARD, LINE)
            frame.text(24, y + 5, item.get("name", "UNNAMED"), WHITE)
            locked = bool(item.get("lockout"))
            if locked:
                frame.text(300, y + 5, "LOCKED", WARN)
            track = GOOD if item.get("on") and not locked else MUTED
            frame.pill(420, y + 3, 38, 13, track); frame.circle(426 if item.get("on") and not locked else 451, y + 9, 5, WHITE)

    def _lights(self, frame: Frame) -> None:
        self._page_heading(frame, "LIGHTS")
        for i, label in enumerate(("DIMMERS", "NON-DIMMERS")):
            x = 16 + i * 232; frame.rounded_rect(x, 92, 216, 110, 14, CARD, LINE)
            self._home_icon(frame, x + 108, 124, 1 if i == 0 else 0)
            frame.text(x + 31, 168, label, WHITE, 2)

    def _dimmers(self, frame: Frame) -> None:
        self._page_heading(frame, "DIMMERS")
        for index, item in enumerate(self.state.get("dimmers", [])):
            y = 82 + index * 26
            percent = self.drag_percent if self.drag_channel == item.get("channel") else int(item.get("percent", 0))
            frame.rounded_rect(12, y, 456, 22, 7, CARD, LINE)
            frame.text(24, y + 6, item.get("name", "UNNAMED"), WHITE)
            frame.fill_rect(145, y + 9, 250, 5, MUTED); frame.fill_rect(145, y + 9, int(250 * percent / 100), 5, CYAN)
            frame.circle(145 + int(250 * percent / 100), y + 11, 6, WHITE); frame.text(412, y + 6, f"{percent}%", WHITE)

    def _network(self, frame: Frame) -> None:
        self._page_heading(frame, "NETWORK"); network = self.state.get("network", {})
        frame.rounded_rect(16, 82, 448, 218, 14, CARD, LINE)
        for i, (label, key) in enumerate((("HOST", "hostname"), ("IPV4", "ipv4"), ("LINK", "link"), ("HCM", "hcm"), ("SYNC", "last_sync"))):
            y = 104 + i * 34; frame.text(30, y, label, MUTED); frame.text(150, y, network.get(key, "UNKNOWN"), WHITE)
            if i < 4: frame.fill_rect(28, y + 20, 424, 1, PANEL)

    def _settings(self, frame: Frame) -> None:
        self._page_heading(frame, "SETTINGS"); settings = self.state.get("settings", {})
        frame.rounded_rect(16, 82, 448, 218, 14, CARD, LINE)
        rows = [("TIMEOUT", f"{settings.get('inactivity_seconds', 10)} SEC"), ("BRIGHTNESS", f"{settings.get('display_brightness', 'UNKNOWN')}%"), ("ROLE", settings.get("role", "UNKNOWN")), ("SIMULATION", settings.get("simulation", "UNKNOWN")), ("PROFILE", settings.get("hardware_profile", "UNKNOWN"))]
        for i, (label, value) in enumerate(rows):
            y = 100 + i * 34
            frame.text(30, y, label, MUTED)
            if i == 0:
                frame.rounded_rect(190, y - 5, 58, 24, 6, CARD, LINE); frame.text(202, y + 2, value, WHITE)
                frame.rounded_rect(258, y - 5, 32, 24, 6, PANEL, LINE); frame.text(270, y + 2, "-", WHITE)
                frame.rounded_rect(298, y - 5, 32, 24, 6, PANEL, LINE); frame.text(310, y + 2, "+", WHITE)
            else:
                frame.text(190, y, value, WHITE)
            if i < len(rows) - 1: frame.fill_rect(28, y + 20, 424, 1, PANEL)
        frame.text(30, 278, "TIMEOUT ONLY", WARN)

    def _rooms(self, frame: Frame) -> None:
        self._page_heading(frame, "RMC DATA")
        for index, room in enumerate(self.state.get("rooms", [])[:5]):
            y = 82 + index * 46; frame.rounded_rect(12, y, 456, 40, 9, CARD, LINE)
            frame.text(24, y + 7, room.get("name", "ROOM"), WHITE); frame.text(24, y + 24, "OFFLINE" if not room.get("online") else "ONLINE", WARN if not room.get("online") else GOOD)
            frame.text(180, y + 8, f"T {room.get('temperature_f', 'UNAVAILABLE')}", MUTED); frame.text(330, y + 8, f"H {room.get('humidity_pct', 'UNAVAILABLE')}", MUTED)

    async def touch(self, event: Any) -> None:
        if not event.points: return
        self.last_touch = time.monotonic()
        point = event.points[0]; x, y = point.x, point.y
        if event.kind == "down":
            if self.page != "home" and y < 66: self.page = "home"; await self.draw(); return
            if self.page == "dimmers":
                index = (y - 82) // 26
                items = self.state.get("dimmers", [])
                if 0 <= index < len(items): self.drag_channel = items[index].get("channel"); self.drag_percent = max(0, min(100, int((x - 145) * 100 / 260))); await self.draw(); return
            await self._tap(x, y)
        elif event.kind == "move" and self.drag_channel:
            self.drag_percent = max(0, min(100, int((x - 145) * 100 / 260))); await self.draw()
        elif event.kind in {"up", "cancel"} and self.drag_channel:
            channel, percent = self.drag_channel, self.drag_percent; self.drag_channel = None; await self.command({"kind": "dimmer", "channel": channel, "value": percent})

    async def _tap(self, x: int, y: int) -> None:
        if self.page == "home":
            if y >= 144: self.page = ("status", "relays" if self.role == "RCM" else ("lights" if self.role == "LCM" else "rmc-data"), "network", "settings")[0 if x < 240 and y < 216 else 1 if x >= 240 and y < 216 else 2 if x < 240 else 3]
        elif self.page == "relays":
            if self.role == "RCM" and 100 <= y < 128:
                self.bank = max(0, min(3, (x - 10) // 117)); await self.command({"kind": "bank_select", "bank": self.bank}); return
            items = [i for i in self.state.get("relays", []) if self.role != "RCM" or (int(i.get("position", 1)) - 1) // 8 == self.bank]
            index = (y - (118 if self.role == "RCM" else 82)) // 22
            if 0 <= index < len(items) and not items[index].get("lockout"): await self.command({"kind": "relay", "channel": items[index].get("channel"), "value": not items[index].get("on", False)}); return
        elif self.page == "lights": self.page = "dimmers" if x < 240 else "non-dimmers"
        elif self.page == "settings" and 110 <= y < 150:
            current = int(self.state.get("settings", {}).get("inactivity_seconds", 10))
            if 258 <= x < 298: current = max(1, current - 1)
            elif 298 <= x < 340: current = min(300, current + 1)
            else: return
            await self.command({"kind": "setting", "setting": "screen_timeout", "value": current})
        await self.draw()


async def run(role: str, mode: str) -> None:
    hardware = importlib.import_module("10_scripts.touchscreen_hardware")
    service = hardware.create_service(role, mode)
    display = touch = None
    ui = None
    stop = asyncio.Event(); loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(signum, stop.set)
        except NotImplementedError: pass
    try:
        display = service.create_display(); touch = service.create_touch(); ui = NativeUI(role, display)
        await display.initialize(); await touch.initialize(); await ui.refresh(); await ui.draw()

        async def poll() -> None:
            while not stop.is_set():
                await asyncio.sleep(3)
                await ui.refresh()
                if ui.page != "home" and time.monotonic() - ui.last_touch >= ui.timeout_seconds:
                    ui.page, ui.bank, ui.scroll = "home", 0, 0
                await ui.draw()

        poll_task = asyncio.create_task(poll())
        while not stop.is_set():
            event = await touch.read_event()
            if event: await ui.touch(event)
    finally:
        if "poll_task" in locals():
            poll_task.cancel()
        if touch is not None:
            await touch.close()
        if display is not None:
            await display.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--role", choices=("RCM", "LCM", "SIM"), default="SIM"); parser.add_argument("--mode", choices=("simulated", "orange_pi"), default="simulated")
    args = parser.parse_args(); asyncio.run(run(args.role, args.mode))
