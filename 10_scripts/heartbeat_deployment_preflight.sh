#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
target="${2:-}"
case "$mode" in
  baseline|strict) ;;
  *) echo "usage: $0 {baseline|strict} {conflict|jetson|lab1}" >&2; exit 64 ;;
esac
case "$target" in
  conflict|jetson|lab1) ;;
  *) echo "usage: $0 {baseline|strict} {conflict|jetson|lab1}" >&2; exit 64 ;;
esac

config="${HC_HEARTBEAT_CONFIG:-/etc/hcm-heartbeat/config.json}"
db="${HC_HEARTBEAT_DB:-/var/lib/hcm-heartbeat/registry.sqlite3}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
case "$target" in
  conflict) template="${HC_HEARTBEAT_TEMPLATE:-${repo_root}/00_Heartbeat/config-conflict.json}" ;;
  jetson) template="${HC_HEARTBEAT_TEMPLATE:-${repo_root}/00_Heartbeat/config-jetson.json}" ;;
  lab1) template="${HC_HEARTBEAT_TEMPLATE:-${repo_root}/00_Heartbeat/config-lab1.json}" ;;
esac

echo "Heartbeat ${mode} preflight for ${target}"
echo "This script is read-only and does not restart services."

python3 --version

if [ ! -r "$config" ]; then
  echo "missing readable config: $config" >&2
  exit 1
fi
python3 -m json.tool "$config" >/dev/null
echo "config JSON OK: $config"

python3 - "$mode" "$config" "$template" <<'PY'
import json
import os
import stat
import sys

mode, config_path, template_path = sys.argv[1:4]
cfg = json.load(open(config_path))
auth_mode = cfg.get("heartbeat_auth_mode", "none")
print("heartbeat_auth_mode={}".format(auth_mode))

if mode == "baseline":
    if auth_mode == "none":
        print("baseline: legacy unauthenticated config detected; inventory only, not deployment-approved")
    elif auth_mode == "hmac-sha256":
        print("baseline: authenticated config detected")
    else:
        print("baseline: unsupported auth mode detected: {}".format(auth_mode))
    sys.exit(0)

if auth_mode != "hmac-sha256":
    raise SystemExit("strict preflight requires heartbeat_auth_mode=hmac-sha256")
secret = cfg.get("heartbeat_auth_secret_file")
if not secret:
    raise SystemExit("strict preflight requires heartbeat_auth_secret_file")
if not os.path.exists(secret):
    raise SystemExit("missing heartbeat auth secret: {}".format(secret))
st = os.stat(secret)
if stat.S_IMODE(st.st_mode) & 0o077:
    raise SystemExit("heartbeat auth secret must not be group/world readable: {}".format(secret))
print("heartbeat auth secret present with restricted mode")

if not os.path.exists(template_path):
    raise SystemExit("missing template for strict comparison: {}".format(template_path))
template = json.load(open(template_path))
keys = [
    "role",
    "bind_address",
    "advertise_ip",
    "port",
    "identity_interface",
    "heartbeat_auth_mode",
    "heartbeat_auth_secret_file",
    "conflict_address",
    "conflict_hostname",
    "conflict_device_id",
    "allowed_device_ids",
    "authorized_devices",
]
mismatches = []
for key in keys:
    if key in template and cfg.get(key) != template.get(key):
        mismatches.append("{}: installed={!r} template={!r}".format(key, cfg.get(key), template.get(key)))
if mismatches:
    raise SystemExit("strict preflight config mismatch:\n" + "\n".join(mismatches))
print("strict config matches template for deployment-critical fields")
PY

if command -v systemctl >/dev/null 2>&1; then
  systemctl --no-pager status hcm-heartbeat.service || true
fi

if [ -e "$db" ]; then
  python3 - "$db" <<'PY'
import sqlite3
import sys

db = sys.argv[1]
conn = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
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

echo "${mode} preflight complete"
