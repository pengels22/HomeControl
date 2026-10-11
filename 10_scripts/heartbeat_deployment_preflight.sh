#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
case "$target" in
  conflict|jetson|lab1) ;;
  *) echo "usage: $0 {conflict|jetson|lab1}" >&2; exit 64 ;;
esac

config="${HC_HEARTBEAT_CONFIG:-/etc/hcm-heartbeat/config.json}"
db="${HC_HEARTBEAT_DB:-/var/lib/hcm-heartbeat/registry.sqlite3}"

echo "Heartbeat deployment preflight for ${target}"
echo "This script is read-only and does not restart services."

python3 --version

if [ ! -r "$config" ]; then
  echo "missing readable config: $config" >&2
  exit 1
fi
python3 -m json.tool "$config" >/dev/null
echo "config JSON OK: $config"

python3 - "$config" <<'PY'
import json
import os
import sys

cfg = json.load(open(sys.argv[1]))
mode = cfg.get("heartbeat_auth_mode", "none")
if mode != "hmac-sha256":
    raise SystemExit("heartbeat_auth_mode must be hmac-sha256 for staged deployment")
secret = cfg.get("heartbeat_auth_secret_file")
if not secret:
    raise SystemExit("heartbeat_auth_secret_file is required")
if not os.path.exists(secret):
    raise SystemExit("missing heartbeat auth secret: {}".format(secret))
st = os.stat(secret)
if st.st_mode & 0o077:
    raise SystemExit("heartbeat auth secret must not be group/world readable: {}".format(secret))
print("heartbeat auth secret present with restricted mode")
PY

if command -v systemctl >/dev/null 2>&1; then
  systemctl --no-pager status hcm-heartbeat.service || true
fi

if [ -e "$db" ]; then
  python3 - "$db" <<'PY'
import sqlite3
import sys

db = sys.argv[1]
conn = sqlite3.connect(db)
try:
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit("SQLite integrity_check failed: {}".format(result))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print("SQLite registry OK; tables: {}".format(", ".join(sorted(tables))))
finally:
    conn.close()
PY
else
  echo "registry database does not exist yet: $db"
fi

echo "preflight complete"
