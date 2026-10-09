#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run: sudo ./install.sh jetson|conflict' >&2; exit 1; fi
case "${1:-}" in
 jetson) CFG=config-jetson.json ;;
 conflict) CFG=config-conflict.json ;;
 *) echo 'Usage: sudo ./install.sh jetson|conflict' >&2; exit 1 ;;
esac
cd "$(dirname "$0")"
python3 - <<'PY'
import ast
ast.parse(open('hcm_heartbeat.py').read())
PY
mkdir -p /usr/local/lib/hcm-heartbeat /etc/hcm-heartbeat
install -m 755 hcm_heartbeat.py /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py
install -m 755 hcm-heartbeat /usr/local/bin/hcm-heartbeat
if [ -e /etc/hcm-heartbeat/config.json ]; then
    echo 'Existing v3 config preserved; check new template manually.'
else
    install -m 600 "$CFG" /etc/hcm-heartbeat/config.json
fi
install -m 644 hcm-heartbeat.service /etc/systemd/system/hcm-heartbeat.service
python3 -m json.tool /etc/hcm-heartbeat/config.json >/dev/null
systemctl daemon-reload
systemctl enable hcm-heartbeat.service
systemctl restart hcm-heartbeat.service
systemctl --no-pager status hcm-heartbeat.service || true
