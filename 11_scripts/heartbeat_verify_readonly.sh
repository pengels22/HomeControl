#!/usr/bin/env bash
set -euo pipefail

endpoint="${1:-http://127.0.0.1:6004}"
db="${HC_HEARTBEAT_DB:-/var/lib/hcm-heartbeat/registry.sqlite3}"

echo "Read-only heartbeat verification against ${endpoint}"
curl -fsS "${endpoint%/}/status" | python3 -m json.tool >/tmp/homecontrol-heartbeat-status.json
python3 - <<'PY'
import json

data = json.load(open('/tmp/homecontrol-heartbeat-status.json'))
print("protocol={} version={} device_id={} hostname={}".format(
    data.get("protocol"),
    data.get("version"),
    data.get("device_id"),
    data.get("hostname"),
))
registry = data.get("status", {}).get("registry", {})
if registry:
    print("registry devices: {}".format(", ".join(sorted(registry))))
else:
    print("registry not present in status response")
PY

if [ -e "$db" ]; then
  python3 - "$db" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
try:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit("registry integrity_check={}".format(integrity))
    print("registry integrity: ok")
    for table in ("authorized_devices", "devices", "communication_faults", "heartbeat_events"):
        try:
            count = conn.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
        except sqlite3.Error as exc:
            print("{} unavailable: {}".format(table, exc))
        else:
            print("{} rows: {}".format(table, count))
finally:
    conn.close()
PY
fi
