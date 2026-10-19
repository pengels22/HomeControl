#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run: sudo ./install.sh jetson|conflict|lab1' >&2; exit 1; fi
case "${1:-}" in
 jetson) TARGET=jetson; CFG=config-jetson.json ;;
 conflict) TARGET=conflict; CFG=config-conflict.json ;;
 lab1) TARGET=lab1; CFG=config-lab1.json ;;
 *) echo 'Usage: sudo ./install.sh jetson|conflict|lab1' >&2; exit 1 ;;
esac
cd "$(dirname "$0")"
if [ ! -f ../homecontrol_identity.py ]; then
    echo 'Missing ../homecontrol_identity.py; run installer from a complete HomeControl checkout.' >&2
    exit 1
fi
python3 - <<'PY'
import ast
for path in ('hcm_heartbeat.py', 'gpio_inputs.py', '../homecontrol_identity.py'):
    with open(path) as f:
        ast.parse(f.read(), filename=path)
PY
VALIDATE_CFG="$CFG"
if [ -e /etc/hcm-heartbeat/config.json ]; then
    VALIDATE_CFG=/etc/hcm-heartbeat/config.json
fi
python3 - "$VALIDATE_CFG" <<'PY'
import json
import os
import sys
cfg = json.load(open(sys.argv[1]))
if cfg.get('heartbeat_auth_mode') != 'hmac-sha256':
    raise SystemExit('heartbeat_auth_mode must be hmac-sha256 for staged deployment')
path = cfg.get('heartbeat_auth_secret_file')
if not path:
    raise SystemExit('heartbeat_auth_secret_file is required for hmac-sha256')
if not os.path.exists(path):
    raise SystemExit('missing heartbeat auth secret {}; provision it outside Git before install'.format(path))
mode = os.stat(path).st_mode
if mode & 0o077:
    raise SystemExit('heartbeat auth secret must not be group/world readable: {}'.format(path))
PY
if [ "$TARGET" = "lab1" ]; then
    echo 'LAB1 mode installs only hcm-heartbeat.service and heartbeat files.'
    echo 'It does not touch homecontrol-lab.service, /opt/homecontrol-lab, hostname, networking, certificates, or simulation role.'
fi
if [ "${HC_DRY_RUN:-0}" = "1" ]; then
    echo "Dry run OK for ${TARGET} using ${CFG}; no files installed and no services changed."
    exit 0
fi
mkdir -p /usr/local/lib/hcm-heartbeat /etc/hcm-heartbeat
install -m 755 hcm_heartbeat.py /usr/local/lib/hcm-heartbeat/hcm_heartbeat.py
install -m 644 gpio_inputs.py /usr/local/lib/hcm-heartbeat/gpio_inputs.py
install -m 644 ../homecontrol_identity.py /usr/local/lib/hcm-heartbeat/homecontrol_identity.py
if [ "$TARGET" = "conflict" ]; then
    install -m 644 ../06_config/07_CONFLICT/hardware_pins.yaml /etc/hcm-heartbeat/hardware_pins.yaml
fi
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
if [ "${HC_SKIP_START:-0}" != "1" ]; then
    systemctl restart hcm-heartbeat.service
    systemctl --no-pager status hcm-heartbeat.service || true
else
    echo 'HC_SKIP_START=1 set; hcm-heartbeat.service was not restarted.'
fi
