#!/usr/bin/env python3
from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path

common_can = import_module("07_servises.common.can")
common_cfg = import_module("07_servises.common.config")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure SIM SocketCAN interfaces.")
    parser.add_argument("--config", default="/etc/homecontrol/02_SIM/sim.yaml")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cfg = common_cfg.load_yaml(Path(args.config))
    result = common_can.configure_sync(cfg, apply=args.apply)
    for name, details in result.items():
        print(f"{name}: {details}")


if __name__ == "__main__":
    main()
