"""Shared HomeControl device identity helpers.

The canonical device ID is a designated physical-interface MAC address,
normalized to 12 lowercase hexadecimal characters with no separators.
This module is intentionally standard-library-only so it can be used by the
Python 3.6 heartbeat daemon and newer HCM services alike.
"""
import re


DEVICE_ID_RE = re.compile(r"^[0-9a-f]{12}$")
COLON_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
HYPHEN_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(-[0-9a-fA-F]{2}){5}$")
PLAIN_MAC_RE = re.compile(r"^[0-9a-fA-F]{12}$")


class InvalidDeviceId(ValueError):
    pass


def normalize_device_id(value):
    if not isinstance(value, str):
        raise InvalidDeviceId("device ID must be a string")
    raw = value.strip()
    if COLON_MAC_RE.match(raw) or HYPHEN_MAC_RE.match(raw):
        normalized = raw.replace(":", "").replace("-", "").lower()
    elif PLAIN_MAC_RE.match(raw):
        normalized = raw.lower()
    else:
        raise InvalidDeviceId("device ID must be a MAC address")
    validate_device_id(normalized)
    return normalized


def validate_device_id(value):
    if not isinstance(value, str) or not DEVICE_ID_RE.match(value):
        raise InvalidDeviceId("device ID must be 12 lowercase hexadecimal characters")
    if value == "000000000000":
        raise InvalidDeviceId("all-zero MAC is invalid")
    if value == "ffffffffffff":
        raise InvalidDeviceId("broadcast MAC is invalid")
    first_octet = int(value[0:2], 16)
    if first_octet & 0x01:
        raise InvalidDeviceId("multicast MAC is invalid")
    return value


def maybe_normalize_device_id(value):
    if value in (None, ""):
        return None
    return normalize_device_id(value)
