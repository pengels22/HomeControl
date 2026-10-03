from __future__ import annotations

import base64
import hashlib
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_MAGIC = "HCMFW"
PACKAGE_VERSION = 1
TARGET_MODULE = "RMC"
DEFAULT_BLOCK_SIZE = 4

RMC_FIRMWARE_COMMANDS = {
    "UPDATE_ENTER_BOOTLOADER": 0x01,
    "BOOTLOADER_READY": 0x02,
    "UPDATE_BEGIN": 0x03,
    "UPDATE_DATA": 0x04,
    "UPDATE_ACK": 0x05,
    "UPDATE_NACK": 0x06,
    "UPDATE_STATUS": 0x07,
    "UPDATE_END": 0x08,
    "UPDATE_VERIFY": 0x09,
    "UPDATE_VALID": 0x0A,
    "UPDATE_FAILED": 0x0B,
    "UPDATE_REBOOT": 0x0C,
    "APPLICATION_ONLINE": 0x0D,
}

SIM_TO_RMC_UPDATE_BASE_ID = 0x600
RMC_TO_SIM_UPDATE_BASE_ID = 0x680

SIM_UPDATE_STATES = [
    "IDLE",
    "RECEIVING_FIRMWARE",
    "VALIDATING_PACKAGE",
    "READY",
    "REQUESTING_BOOTLOADER",
    "WAITING_FOR_BOOTLOADER",
    "BEGINNING_UPDATE",
    "TRANSFERRING",
    "VERIFYING",
    "REBOOTING",
    "WAITING_FOR_APPLICATION",
    "VERIFYING_VERSION",
    "COMPLETE",
    "FAILED",
    "RECOVERY_REQUIRED",
]

HCM_UPDATE_STATES = [
    "QUEUED",
    "SENDING_TO_SIM",
    "SIM_STAGED",
    "RMC_ENTERING_BOOTLOADER",
    "TRANSFERRING",
    "VERIFYING",
    "REBOOTING",
    "WAITING_FOR_RMC",
    "COMPLETE",
    "FAILED",
    "RECOVERY_REQUIRED",
]


class FirmwarePackageError(ValueError):
    pass


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def crc32_hex(data: bytes) -> str:
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_image(encoded: str) -> bytes:
    try:
        return base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception as exc:
        raise FirmwarePackageError("firmware image is not valid base64") from exc


def make_package(
    *,
    image: bytes,
    firmware_version: str,
    hardware_revision: str = "RMC-NANO-ATMEGA328P",
    session_id: str | None = None,
    build_id: str | None = None,
) -> dict[str, Any]:
    return {
        "magic": PACKAGE_MAGIC,
        "package_version": PACKAGE_VERSION,
        "target_module": TARGET_MODULE,
        "hardware_revision": hardware_revision,
        "firmware_version": firmware_version,
        "image_length": len(image),
        "image_sha256": sha256_hex(image),
        "image_crc32": crc32_hex(image),
        "image_b64": encode_image(image),
        "build_id": build_id,
        "session_id": session_id or str(uuid.uuid4()),
        "created_at": time.time(),
    }


def validate_package(package: dict[str, Any], *, compatible_hardware: list[str] | None = None) -> bytes:
    if package.get("magic") != PACKAGE_MAGIC:
        raise FirmwarePackageError("invalid firmware package magic")
    if int(package.get("package_version", 0)) != PACKAGE_VERSION:
        raise FirmwarePackageError("unsupported firmware package version")
    if str(package.get("target_module", "")).upper() != TARGET_MODULE:
        raise FirmwarePackageError("firmware package target is not RMC")
    hardware_revision = str(package.get("hardware_revision", ""))
    if compatible_hardware and hardware_revision not in compatible_hardware:
        raise FirmwarePackageError(f"incompatible RMC hardware revision: {hardware_revision}")
    image = decode_image(str(package.get("image_b64", "")))
    expected_length = int(package.get("image_length", -1))
    if expected_length <= 0 or expected_length != len(image):
        raise FirmwarePackageError("firmware image length mismatch")
    if package.get("image_sha256") != sha256_hex(image):
        raise FirmwarePackageError("firmware image sha256 mismatch")
    expected_crc = package.get("image_crc32")
    if expected_crc and str(expected_crc).lower() != crc32_hex(image):
        raise FirmwarePackageError("firmware image crc32 mismatch")
    return image


def update_arbitration_id(node_id: int, *, response: bool = False) -> int:
    if node_id < 0 or node_id > 15:
        raise ValueError("RMC node id must be 0-15")
    base = RMC_TO_SIM_UPDATE_BASE_ID if response else SIM_TO_RMC_UPDATE_BASE_ID
    return base | ((node_id & 0x0F) << 4)


def session_byte(session_id: str) -> int:
    digest = hashlib.sha256(session_id.encode("utf-8")).digest()
    return digest[0]


def control_frame(command: str, node_id: int, session_id: str, value: int = 0) -> dict[str, Any]:
    code = RMC_FIRMWARE_COMMANDS[command]
    return {
        "arbitration_id": update_arbitration_id(node_id),
        "command": command,
        "data": [
            code,
            session_byte(session_id),
            (value >> 8) & 0xFF,
            value & 0xFF,
            0,
            0,
            0,
            0,
        ],
    }


def data_frames(image: bytes, node_id: int, session_id: str, block_size: int = DEFAULT_BLOCK_SIZE) -> list[dict[str, Any]]:
    if block_size < 1 or block_size > 4:
        raise ValueError("classical CAN firmware block size must be 1-4 bytes")
    frames = []
    seq = 0
    for offset in range(0, len(image), block_size):
        chunk = list(image[offset: offset + block_size])
        padded = chunk + [0] * (4 - len(chunk))
        frames.append({
            "arbitration_id": update_arbitration_id(node_id),
            "command": "UPDATE_DATA",
            "sequence": seq,
            "offset": offset,
            "payload_length": len(chunk),
            "data": [
                RMC_FIRMWARE_COMMANDS["UPDATE_DATA"],
                session_byte(session_id),
                (seq >> 8) & 0xFF,
                seq & 0xFF,
                *padded,
            ],
        })
        seq += 1
    return frames


def update_frame_plan(image: bytes, node_id: int, session_id: str) -> list[dict[str, Any]]:
    frames = [
        control_frame("UPDATE_ENTER_BOOTLOADER", node_id, session_id),
        control_frame("UPDATE_BEGIN", node_id, session_id, len(image)),
    ]
    frames.extend(data_frames(image, node_id, session_id))
    frames.extend([
        control_frame("UPDATE_END", node_id, session_id),
        control_frame("UPDATE_VERIFY", node_id, session_id),
        control_frame("UPDATE_REBOOT", node_id, session_id),
    ])
    return frames


@dataclass
class RmcFirmwareUpdateSession:
    session_id: str
    target_rmc_id: str
    node_id: int
    can_interface: str
    firmware_version: str
    state: str = "IDLE"
    progress_pct: int = 0
    error: str | None = None
    frames_sent: int = 0
    retries: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, state: str, progress_pct: int | None = None, detail: dict[str, Any] | None = None) -> None:
        if state not in SIM_UPDATE_STATES:
            raise ValueError(f"invalid SIM update state {state}")
        self.state = state
        if progress_pct is not None:
            self.progress_pct = max(0, min(100, int(progress_pct)))
        self.history.append({
            "ts": time.time(),
            "state": self.state,
            "progress_pct": self.progress_pct,
            "detail": detail or {},
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_rmc_id": self.target_rmc_id,
            "node_id": self.node_id,
            "can_interface": self.can_interface,
            "firmware_version": self.firmware_version,
            "state": self.state,
            "progress_pct": self.progress_pct,
            "error": self.error,
            "frames_sent": self.frames_sent,
            "retries": self.retries,
            "history": self.history[-20:],
        }


def stage_package(staging_root: Path, package: dict[str, Any], image: bytes) -> Path:
    session_id = str(package["session_id"])
    staging_root.mkdir(parents=True, exist_ok=True)
    tmp = staging_root / f"{session_id}.bin.tmp"
    final = staging_root / f"{session_id}.bin"
    tmp.write_bytes(image)
    tmp.replace(final)
    return final
