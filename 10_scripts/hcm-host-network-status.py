#!/usr/bin/env python3
"""Write a read-only snapshot of the host's network interfaces for HCM."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List


def _ip_json(args: List[str]) -> List[Dict[str, Any]]:
    ip = shutil.which("ip") or "/usr/sbin/ip"
    result = subprocess.run(
        [ip, "-j"] + args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    try:
        value = json.loads(result.stdout)
        return value if isinstance(value, list) else []
    except ValueError:
        if args != ["route", "show", "default"]:
            raise
        routes = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields or fields[0] != "default":
                continue
            route = {}
            for key, marker in (("gateway", "via"), ("dev", "dev"), ("metric", "metric")):
                if marker in fields:
                    index = fields.index(marker)
                    if index + 1 < len(fields):
                        route[key] = int(fields[index + 1]) if key == "metric" else fields[index + 1]
            routes.append(route)
        return routes


def collect_status() -> Dict[str, Any]:
    addresses = _ip_json(["address", "show"])
    routes = _ip_json(["route", "show", "default"])
    defaults = {}
    for route in routes:
        interface = route.get("dev")
        if not interface or interface in defaults:
            continue
        defaults[interface] = {
            key: route[key]
            for key in ("gateway", "dev", "metric", "protocol")
            if route.get(key) is not None
        }
    interfaces = []
    for item in addresses:
        name = item.get("ifname")
        if not name:
            continue
        ipv4 = []
        ipv6 = []
        for address in item.get("addr_info") or []:
            family = address.get("family")
            local = address.get("local")
            prefix = address.get("prefixlen")
            if not local:
                continue
            value = f"{local}/{prefix}" if prefix is not None else str(local)
            if family == "inet":
                ipv4.append(value)
            elif family == "inet6":
                ipv6.append(value)
        route = defaults.get(name)
        interfaces.append({
            "name": name,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "status": str(item.get("operstate") or "Unknown").title(),
            "network": ipv4[0].split("/", 1)[1] if ipv4 and "/" in ipv4[0] else None,
            "default_route": route,
        })
    default_route = next(iter(defaults.values()), None)
    return {
        "version": 1,
        "updated_at": time.time(),
        "interfaces": interfaces,
        "default_route": default_route,
    }


def write_status(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(collect_status(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_status(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
