from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "07_config" / "10_Common"


def _load_common(name: str):
    if name in sys.modules:
        return sys.modules[name]
    path = COMMON / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load deployment module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def select_deployment_package(device_type: str, *, device_id: str | None = None, hardware_platform: str | None = None) -> str:
    """Return the approved 07_config package for a discovered device.

    This is planning-only commissioning integration. It never grants SSH access,
    executes scripts, or changes device state.
    """

    inventory = _load_common("inventory")
    return inventory.package_for_device(device_type, device_id=device_id, hardware_platform=hardware_platform)


def commissioning_plan(device_type: str, *, device_id: str, hardware_platform: str | None = None) -> dict[str, str]:
    package = select_deployment_package(device_type, device_id=device_id, hardware_platform=hardware_platform)
    return {
        "device_id": device_id,
        "requested_device_type": device_type.upper(),
        "deployment_package": package,
        "status": "pending_admin_approval",
        "remote_execution": "not authorized",
    }
