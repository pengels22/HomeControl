from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COMMON = ROOT / "07_config" / "10_Common"


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
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--target", choices=sorted(inventory_mod.inventory().keys()))
    preflight.add_argument("--remote", action="store_true", required=True, help="run read-only remote compatibility checks")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--target", choices=sorted(inventory_mod.inventory().keys()))
    verify.add_argument("--remote", action="store_true", help="run read-only SSH verification")
    subparsers.add_parser("history")

    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--target", choices=sorted(inventory_mod.inventory().keys()))
    deploy.add_argument("--all", action="store_true", help="explicitly approve a fleet-wide live deployment")
    deploy.add_argument("--release")
    deploy.add_argument("--dry-run", action="store_true")
    deploy.add_argument("--yes", action="store_true", help="execute the approved SSH deployment plan")
    deploy.add_argument("--skip-tests", action="store_true", help="skip local repository tests before live deployment")

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--target", required=True, choices=sorted(inventory_mod.inventory().keys()))
    rollback.add_argument("--deployment-id", help="deployment report ID whose recovery point should be restored")
    rollback.add_argument("--yes", action="store_true", help="execute adapter rollback over SSH")
    return parser


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _exit_for_report(report) -> int:
    status = report.get("summary", {}).get("status", report.get("status"))
    return 1 if status in {"FAIL", "MANUAL INTERVENTION REQUIRED", "ROLLED BACK"} else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        _print_json({name: inventory_mod.entry_to_dict(entry) for name, entry in inventory_mod.inventory().items()})
        return 0

    if args.command == "status":
        manifests = manifest.load_all_manifests(ROOT / "07_config")
        data = {
            "repository": str(ROOT),
            "manifests": {device_type: item.package for device_type, item in sorted(manifests.items())},
            "remote_execution": "not_contacted",
        }
        if args.remote:
            data["remote"] = engine.verify(repo_root=ROOT)
            data["remote_execution"] = "ssh_read_only"
        _print_json(data)
        return _exit_for_report(data.get("remote", {"summary": {"status": "PASS"}}))

    if args.command == "preflight":
        report = engine.preflight(repo_root=ROOT, target=args.target)
        _print_json(report)
        return _exit_for_report(report)

    if args.command == "deploy":
        if args.target and args.all:
            parser.error("deploy requires either --target DEVICE or --all, not both")
        if args.yes and not args.target and not args.all:
            parser.error("live deployment requires --target DEVICE --yes or --all --yes")
        dry_run = args.dry_run or not args.yes
        report = engine.deploy(
            repo_root=ROOT,
            release=args.release,
            target=args.target,
            dry_run=dry_run,
            explicit_all=args.all,
            run_tests=not args.skip_tests,
        )
        path = engine.write_report(ROOT, report)
        report["report_path"] = str(path)
        _print_json(report)
        return _exit_for_report(report)

    if args.command == "verify":
        if args.remote:
            report = engine.verify(repo_root=ROOT, target=args.target)
        else:
            report = engine.plan_deployment(repo_root=ROOT, target=args.target, dry_run=True)
            report["verification_scope"] = "manifest, inventory, release planning"
        _print_json(report)
        return _exit_for_report(report)

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
                    "detail": "rollback requires --yes and --deployment-id for the deployment report to restore",
                }
            )
            return 0
        if not args.deployment_id:
            parser.error("rollback --yes requires --deployment-id; refusing to guess a recovery point")
        try:
            report = engine.rollback(repo_root=ROOT, target=args.target, deployment_id=args.deployment_id)
        except engine.DeploymentError as exc:
            _print_json({"target": args.target, "status": "FAIL", "detail": str(exc), "summary": {"status": "FAIL"}})
            return 1
        _print_json(report)
        return _exit_for_report(report)

    parser.error(f"unsupported command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
