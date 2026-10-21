from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PinMapEntry:
    channel: str
    hardware_address: str
    function: str
    field_voltage: str


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def load_pinout(path: str | Path) -> dict[str, PinMapEntry]:
    pinout_path = Path(path)
    entries: dict[str, PinMapEntry] = {}
    if not pinout_path.exists():
        return entries
    for line in pinout_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = _split_row(stripped)
        if len(cells) < 4:
            continue
        if cells[0].lower() in {"channel", "relay", "pin"}:
            continue
        entries[cells[0].upper()] = PinMapEntry(
            channel=cells[0].upper(),
            hardware_address=cells[1],
            function=cells[2],
            field_voltage=cells[3],
        )
    return entries


def require_channels(pinout: dict[str, PinMapEntry], channels: list[str]) -> None:
    missing = [channel for channel in channels if channel not in pinout]
    if missing:
        raise ValueError(f"pinout missing required channels: {', '.join(missing)}")
