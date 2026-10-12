#!/usr/bin/env python3

import argparse
import json
import sys
import time
import urllib.request


EXPECTED_DEVICE_IDS = ("48b02d87db16", "2ccf675d3414")


class HeartbeatStatusError(RuntimeError):
    pass


def load_json_file(path):
    with open(path) as handle:
        return json.load(handle)


def fetch_status(endpoint, timeout):
    url = endpoint.rstrip("/") + "/status"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        status = response.getcode()
        raw = response.read()
    if status != 200:
        raise HeartbeatStatusError("unexpected HTTP status {}".format(status))
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HeartbeatStatusError("invalid status JSON: {}".format(exc))


def verify_status_payload(data, cfg, expected_device_ids=EXPECTED_DEVICE_IDS):
    registry = data.get("status", {}).get("registry")
    if not isinstance(registry, dict):
        raise HeartbeatStatusError("status registry missing or invalid")

    authorized = {
        item.get("device_id"): item
        for item in cfg.get("authorized_devices", [])
        if item.get("device_id")
    }

    missing_registered = [device_id for device_id in expected_device_ids if device_id not in registry]
    if missing_registered:
        raise HeartbeatStatusError("missing registered devices: {}".format(",".join(missing_registered)))

    missing_authorized = [device_id for device_id in expected_device_ids if device_id not in authorized]
    if missing_authorized:
        raise HeartbeatStatusError("missing authorized config entries: {}".format(",".join(missing_authorized)))

    failures = []
    for device_id in expected_device_ids:
        item = registry.get(device_id) or {}
        expected = authorized[device_id]
        if not item.get("authorized"):
            failures.append("{} not authorized in registry".format(device_id))
        if expected.get("hostname") and item.get("hostname") != expected.get("hostname"):
            failures.append("{} hostname {} != {}".format(device_id, item.get("hostname"), expected.get("hostname")))
        if expected.get("ip_address") and item.get("ip_address") != expected.get("ip_address"):
            failures.append("{} ip {} != {}".format(device_id, item.get("ip_address"), expected.get("ip_address")))
        fault = item.get("active_fault")
        if fault and not item.get("maintenance"):
            failures.append("{} active_fault {}".format(device_id, fault.get("code")))

    if failures:
        raise HeartbeatStatusError("; ".join(failures))

    return {
        "registered": list(expected_device_ids),
        "authorized": sorted(authorized),
        "active_faults": "none",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify Conflict heartbeat /status JSON without exposing secrets")
    parser.add_argument("endpoint")
    parser.add_argument("--config", default="/etc/hcm-heartbeat/config.json")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--grace", type=int, default=5)
    args = parser.parse_args(argv)

    if args.grace > 0:
        time.sleep(args.grace)
    cfg = load_json_file(args.config)
    data = fetch_status(args.endpoint, args.timeout)
    result = verify_status_payload(data, cfg)
    print(
        "heartbeat_status_json=ok registered={} authorized={} active_faults={}".format(
            ",".join(result["registered"]),
            ",".join(result["authorized"]),
            result["active_faults"],
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HeartbeatStatusError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
