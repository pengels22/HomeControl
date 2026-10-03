#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

common_can = import_module("07_servises.common.can")
common_cfg = import_module("07_servises.common.config")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure SIM SocketCAN interfaces.")
    parser.add_argument("--config", default="/etc/homecontrol/02_SIM/sim.yaml")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true", help="Print detected SocketCAN interface status.")
    args = parser.parse_args()

    cfg = common_cfg.load_yaml(Path(args.config))
    if args.check:
        result = common_can.socketcan_status(cfg)
        for name, details in result.items():
            print(f"{name}: {details}")
        missing = [name for name, details in result.items() if details["enabled"] and not details["exists"]]
        if missing:
            raise SystemExit(f"missing enabled CAN interface(s): {', '.join(missing)}")
        return

    result = common_can.configure_sync(cfg, apply=args.apply)
    for name, details in result.items():
        print(f"{name}: {details}")


if __name__ == "__main__":
    main()
