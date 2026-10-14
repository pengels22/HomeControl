from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_provider():
    spec = importlib.util.spec_from_file_location(
        "hcm_host_network_status_test",
        ROOT / "10_scripts/hcm-host-network-status.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_host_network_provider_collects_interfaces_and_default_route(tmp_path, monkeypatch):
    provider = load_provider()
    fake_ip = tmp_path / "ip"
    fake_ip.write_text(
        "#!/bin/sh\n"
        "if [ \"$4\" = \"default\" ]; then\n"
        "  printf '%s' '[{\"dev\":\"eth0\",\"gateway\":\"192.168.20.1\",\"metric\":100}]'\n"
        "else\n"
        "  printf '%s' '[{\"ifname\":\"eth0\",\"operstate\":\"UP\",\"addr_info\":[{\"family\":\"inet\",\"local\":\"192.168.20.27\",\"prefixlen\":24},{\"family\":\"inet6\",\"local\":\"fe80::1\",\"prefixlen\":64}]},{\"ifname\":\"spare0\",\"operstate\":\"DOWN\",\"addr_info\":[]}]'\n"
        "fi\n"
    )
    fake_ip.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    result = provider.collect_status()

    eth0 = next(item for item in result["interfaces"] if item["name"] == "eth0")
    spare = next(item for item in result["interfaces"] if item["name"] == "spare0")
    assert eth0["ipv4"] == ["192.168.20.27/24"]
    assert eth0["ipv6"] == ["fe80::1/64"]
    assert eth0["status"] == "Up"
    assert eth0["default_route"]["gateway"] == "192.168.20.1"
    assert spare["status"] == "Down"


def test_host_network_provider_writes_atomically(tmp_path, monkeypatch):
    provider = load_provider()
    fake_ip = tmp_path / "ip"
    fake_ip.write_text("#!/bin/sh\nprintf '%s' '[]'\n")
    fake_ip.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    output = tmp_path / "state" / "network.json"

    provider.write_status(output)

    payload = json.loads(output.read_text())
    assert payload["version"] == 1
    assert payload["interfaces"] == []
    assert payload["updated_at"] > 0
    assert not list(output.parent.glob(".*.network.json.*"))


def test_host_network_provider_accepts_legacy_text_route_output(tmp_path, monkeypatch):
    provider = load_provider()
    fake_ip = tmp_path / "ip"
    fake_ip.write_text(
        "#!/bin/sh\n"
        "if [ \"$4\" = \"default\" ]; then\n"
        "  printf '%s\\n' 'default via 192.168.20.1 dev eth0 metric 100'\n"
        "else\n"
        "  printf '%s' '[]'\n"
        "fi\n"
    )
    fake_ip.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    result = provider.collect_status()

    assert result["default_route"] == {
        "gateway": "192.168.20.1",
        "dev": "eth0",
        "metric": 100,
    }
