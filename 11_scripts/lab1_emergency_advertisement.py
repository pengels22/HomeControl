#!/usr/bin/env python3
"""Safely add LAB1 emergency capability fields to the existing role agent."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


TARGET = Path('/opt/homecontrol-lab/lab_agent.py')
HEARTBEAT_FIELDS = re.compile(
    r'(?m)^(?P<indent>\s*)"physical_outputs_enabled": False,\n'
    r'(?P=indent)"commissioned_local": False,\n'
)


def apply(path: Path = TARGET) -> None:
    source = path.read_text()
    if '"registered_module_type": "RCM"' in source:
        if source.count('"registered_module_type": "RCM"') != 1:
            raise SystemExit('LAB1 registered module type marker was not unique')
        source = source.replace('"registered_module_type": "RCM"', '"registered_module_type": "LCM"', 1)
    if '"emergency_ui"' in source:
        path.write_text(source)
        return
    if len(HEARTBEAT_FIELDS.findall(source)) != 1:
        raise SystemExit('LAB1 role agent heartbeat block did not match exactly')
    def replacement(match):
        indent = match.group('indent')
        return match.group(0) + (
            f'{indent}"emergency_ui": {{\n'
            f'{indent}    "enabled": True,\n'
            f'{indent}    "available": True,\n'
            f'{indent}    "protocol": "http",\n'
            f'{indent}    "port": 6010,\n'
            f'{indent}    "config_path": "/config",\n'
            f'{indent}    "health_path": "/health",\n'
            f'{indent}}},\n'
        )
    updated = HEARTBEAT_FIELDS.sub(replacement, source, count=1)
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, path.stat().st_mode & 0o777)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    apply()
