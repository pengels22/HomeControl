from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COMMON = ROOT / "06_config" / "10_Common"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manifest = _load_module("manifest", COMMON / "manifest.py")
inventory_mod = _load_module("inventory", COMMON / "inventory.py")
release_mod = _load_module("release", COMMON / "release.py")
transport_mod = _load_module("transport", COMMON / "transport.py")
artifact_mod = _load_module("artifact", COMMON / "artifact.py")
adapters_mod = _load_module("adapters", COMMON / "adapters.py")
engine = _load_module("engine", COMMON / "engine.py")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="homecontrol", description="HomeControl deployment manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--remote", action="store_true", help="run read-only SSH status checks")
    subparsers.add_parser("inventory")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--target", choices=sorted(inventory_mod.inventory().keys()))
    verify.add_argument("--remote", action="store_true", help="run read-only SSH verification")
    subparsers.add_parser("history")

    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--target", choices=sorted(inventory_mod.inventory().keys()))
    deploy.add_argument("--release")
    deploy.add_argument("--dry-run", action="store_true")
    deploy.add_argument("--yes", action="store_true", help="execute the approved SSH deployment plan")
    deploy.add_argument("--skip-tests", action="store_true", help="skip local repository tests before live deployment")

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--target", required=True, choices=sorted(inventory_mod.inventory().keys()))
    rollback.add_argument("--yes", action="store_true", help="execute adapter rollback over SSH")
    return parser


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        _print_json({name: inventory_mod.entry_to_dict(entry) for name, entry in inventory_mod.inventory().items()})
        return 0

    if args.command == "status":
        manifests = manifest.load_all_manifests(ROOT / "06_config")
        data = {
            "repository": str(ROOT),
            "manifests": {device_type: item.package for device_type, item in sorted(manifests.items())},
            "remote_execution": "not_contacted",
        }
        if args.remote:
            data["remote"] = engine.verify(repo_root=ROOT)
            data["remote_execution"] = "ssh_read_only"
        _print_json(data)
        return 0

    if args.command == "deploy":
        dry_run = args.dry_run or not args.yes
        report = engine.deploy(
            repo_root=ROOT,
            release=args.release,
            target=args.target,
            dry_run=dry_run,
            run_tests=not args.skip_tests,
        )
        path = engine.write_report(ROOT, report)
        report["report_path"] = str(path)
        _print_json(report)
        return 0

    if args.command == "verify":
        if args.remote:
            report = engine.verify(repo_root=ROOT, target=args.target)
        else:
            report = engine.plan_deployment(repo_root=ROOT, target=args.target, dry_run=True)
            report["verification_scope"] = "manifest, inventory, release planning"
        _print_json(report)
        return 0

    if args.command == "history":
        report_dir = ROOT / "runtime" / "deployments"
        if not report_dir.exists():
            _print_json({"reports": []})
            return 0
        _print_json({"reports": sorted(str(path) for path in report_dir.glob("*.json"))})
        return 0

    if args.command == "rollback":
        if not args.yes:
            _print_json(
                {
                    "target": args.target,
                    "status": "MANUAL INTERVENTION REQUIRED",
                    "detail": "rollback requires --yes and any adapter-specific backup environment variables",
                }
            )
            return 0
        _print_json(engine.rollback(repo_root=ROOT, target=args.target))
        return 0

    parser.error(f"unsupported command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
