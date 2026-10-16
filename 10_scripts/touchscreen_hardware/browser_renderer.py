"""Chromium CDP renderer for the ST7796U display boundary.

This is intentionally separate from module controls. It captures the existing
HTML UI, converts frames to RGB565, and sends only the changed rectangle to the
validated display driver.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class BrowserRendererConfig:
    url: str = "http://127.0.0.1:8765/?role=RCM"
    browser_binary: str = "chromium"
    debug_port: int = 9222
    width: int = 480
    height: int = 320
    capture_interval: float = 0.20
    user_data_dir: Path = Path("tmp/touchscreen-chromium")

    @property
    def debug_url(self) -> str:
        return f"http://127.0.0.1:{self.debug_port}"

    def command(self) -> list[str]:
        return [
            self.browser_binary,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.debug_port}",
            f"--user-data-dir={self.user_data_dir}",
            f"--window-size={self.width},{self.height}",
            self.url,
        ]


@dataclass(frozen=True)
class DisplayUpdate:
    x: int
    y: int
    width: int
    height: int
    rgb565: bytes


@dataclass
class RenderMetrics:
    frames_captured: int = 0
    updates_sent: int = 0
    full_updates: int = 0
    changed_pixels: int = 0
    capture_seconds: float = 0.0
    update_seconds: float = 0.0

    @property
    def capture_fps(self) -> float:
        return self.frames_captured / self.capture_seconds if self.capture_seconds else 0.0


class CdpClient:
    """Small synchronous CDP client; calls are wrapped off-loop by the renderer."""

    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self._socket = None
        self._next_id = 0

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("Chromium renderer requires websocket-client") from exc
        self._socket = websocket.create_connection(self.websocket_url, timeout=5)

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("CDP client is not connected")
        self._next_id += 1
        request_id = self._next_id
        self._socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self._socket.recv())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"CDP {method} failed: {response['error']}")
            return response.get("result", {})

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


class BrowserRenderer:
    def __init__(
        self,
        display,
        config: BrowserRendererConfig = BrowserRendererConfig(),
        process_factory: Callable[..., Any] = subprocess.Popen,
        client_factory: Callable[[str], CdpClient] = CdpClient,
    ) -> None:
        self.display = display
        self.config = config
        self.process_factory = process_factory
        self.client_factory = client_factory
        self.process = None
        self.client: CdpClient | None = None
        self.previous_rgb = None
        self.metrics = RenderMetrics()

    async def start(self) -> None:
        self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.process = self.process_factory(self.config.command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = await asyncio.to_thread(self._wait_for_page)
        self.client = self.client_factory(target["webSocketDebuggerUrl"])
        await asyncio.to_thread(self.client.connect)
        await self._command("Page.enable")
        await self._command("Emulation.setDeviceMetricsOverride", {
            "width": self.config.width,
            "height": self.config.height,
            "deviceScaleFactor": 1,
            "mobile": True,
        })

    async def capture_update(self) -> DisplayUpdate | None:
        if self.client is None:
            raise RuntimeError("browser renderer is not started")
        started = time.perf_counter()
        result = await self._command("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        image = _decode_rgb(result["data"])
        elapsed = time.perf_counter() - started
        self.metrics.frames_captured += 1
        self.metrics.capture_seconds += elapsed
        update = _dirty_update(self.previous_rgb, image, self.config.width, self.config.height)
        self.previous_rgb = image
        if update is not None:
            self.metrics.updates_sent += 1
            self.metrics.changed_pixels += update.width * update.height
            if update.width == self.config.width and update.height == self.config.height:
                self.metrics.full_updates += 1
            started = time.perf_counter()
            await self.display.draw_rgb565(update.x, update.y, update.width, update.height, update.rgb565)
            self.metrics.update_seconds += time.perf_counter() - started
        return update

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        try:
            while stop_event is None or not stop_event.is_set():
                await self.capture_update()
                await asyncio.sleep(self.config.capture_interval)
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.process is not None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    async def _command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("browser renderer is not started")
        return await asyncio.to_thread(self.client.command, method, params)

    def _wait_for_page(self) -> dict[str, Any]:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.config.debug_url}/json", timeout=1) as response:
                    pages = json.load(response)
                for page in pages:
                    if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                        return page
            except OSError:
                time.sleep(0.1)
        raise TimeoutError("Chromium did not expose a CDP page")


def _decode_rgb(encoded_png: str) -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Chromium renderer requires Pillow for PNG decoding") from exc
    with Image.open(BytesIO(base64.b64decode(encoded_png))) as image:
        return image.convert("RGB").tobytes()


def rgb888_to_rgb565(rgb: bytes) -> bytes:
    if len(rgb) % 3:
        raise ValueError("RGB data must contain complete pixels")
    output = bytearray((len(rgb) // 3) * 2)
    destination = 0
    for offset in range(0, len(rgb), 3):
        red, green, blue = rgb[offset], rgb[offset + 1], rgb[offset + 2]
        value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        output[destination] = value >> 8
        output[destination + 1] = value & 0xFF
        destination += 2
    return bytes(output)


def _dirty_update(previous: bytes | None, current: bytes, width: int, height: int) -> DisplayUpdate | None:
    expected = width * height * 3
    if len(current) != expected:
        raise ValueError(f"browser frame must be {width}x{height} RGB")
    if previous is None:
        x, y, right, bottom = 0, 0, width, height
    else:
        if len(previous) != expected:
            raise ValueError("previous browser frame has the wrong size")
        left, top, right, bottom = width, height, -1, -1
        for row in range(height):
            row_start = row * width * 3
            for column in range(width):
                offset = row_start + column * 3
                if current[offset:offset + 3] != previous[offset:offset + 3]:
                    left = min(left, column)
                    top = min(top, row)
                    right = max(right, column)
                    bottom = max(bottom, row)
        if right < 0:
            return None
        x, y, right, bottom = left, top, right + 1, bottom + 1
    pixels = bytearray()
    for row in range(y, bottom):
        start = (row * width + x) * 3
        pixels.extend(rgb888_to_rgb565(current[start:start + (right - x) * 3]))
    return DisplayUpdate(x, y, right - x, bottom - y, bytes(pixels))
