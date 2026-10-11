#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
case "$target" in
  conflict|jetson|lab1) ;;
  *) echo "usage: $0 {conflict|jetson|lab1}" >&2; exit 64 ;;
esac

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="${HC_HEARTBEAT_BACKUP_DIR:-/var/backups/homecontrol-heartbeat/${target}-${stamp}}"
config="${HC_HEARTBEAT_CONFIG:-/etc/hcm-heartbeat/config.json}"
db="${HC_HEARTBEAT_DB:-/var/lib/hcm-heartbeat/registry.sqlite3}"

if [ "$(id -u)" -ne 0 ]; then
  if [ "${HC_ALLOW_NONROOT:-0}" != "1" ]; then
    echo "run with sudo so root-owned heartbeat files can be copied" >&2
    exit 1
  fi
fi

mkdir -p "$dest"
chmod 0700 "$dest"

copy_if_present() {
  src="$1"
  if [ -e "$src" ]; then
    cp -a "$src" "$dest/"
  fi
}

copy_if_present "$config"
copy_if_present /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py
copy_if_present /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
copy_if_present /usr/local/bin/hcm-heartbeat
copy_if_present /etc/systemd/system/hcm-heartbeat.service

if [ -e "$db" ]; then
  python3 - "$db" "${dest}/registry.sqlite3" <<'PY'
import os
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
src_conn = sqlite3.connect("file:{}?mode=ro".format(src), uri=True, timeout=30.0)
dst_conn = sqlite3.connect(dst)
try:
    src_conn.backup(dst_conn)
    dst_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit("backup integrity_check failed: {}".format(result))
finally:
    dst_conn.close()
    src_conn.close()
os.chmod(dst, 0o600)
PY
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --no-pager cat hcm-heartbeat.service >"${dest}/hcm-heartbeat.service.cat" 2>/dev/null || true
  systemctl --no-pager status hcm-heartbeat.service >"${dest}/hcm-heartbeat.service.status" 2>/dev/null || true
fi

cat >"${dest}/RESTORE_NOTES.txt" <<EOF
Heartbeat backup for ${target}
Created: ${stamp}

Rollback outline:
1. Stop hcm-heartbeat.service during an approved maintenance window.
2. Restore files from this directory to their original paths.
3. Restore registry.sqlite3 from the online backup copy. Do not combine it with
   WAL/SHM files from another point in time.
4. Run systemctl daemon-reload.
5. Restart hcm-heartbeat.service.
6. Run heartbeat_deployment_preflight.sh and non-destructive verification.
EOF

echo "$dest"
