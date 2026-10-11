#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-}"
if [ -z "$backup_dir" ] || [ ! -d "$backup_dir" ]; then
  echo "usage: $0 <backup-dir-created-by-heartbeat_backup.sh>" >&2
  exit 64
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo during an approved rollback window" >&2
  exit 1
fi

restore_file() {
  name="$1"
  dest="$2"
  if [ -e "${backup_dir}/${name}" ]; then
    install -D -m "$3" "${backup_dir}/${name}" "$dest"
  fi
}

systemctl stop hcm-heartbeat.service

restore_file config.json /etc/hcm-heartbeat/config.json 0600
restore_file hcm_heartbeat.py /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py 0755
restore_file homecontrol_identity.py /usr/local/lib/hcm-heartbeat/homecontrol_identity.py 0644
restore_file hcm-heartbeat /usr/local/bin/hcm-heartbeat 0755
restore_file hcm-heartbeat.service /etc/systemd/system/hcm-heartbeat.service 0644
restore_file registry.sqlite3 /var/lib/hcm-heartbeat/registry.sqlite3 0644
rm -f /var/lib/hcm-heartbeat/registry.sqlite3-wal /var/lib/hcm-heartbeat/registry.sqlite3-shm

systemctl daemon-reload
systemctl restart hcm-heartbeat.service
systemctl --no-pager status hcm-heartbeat.service || true
