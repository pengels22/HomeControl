#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${HC_INSTALL_ROOT:-/opt/HomeControl}"
CAN_SERVICE="homecontrol-sim-can.service"
MODULES_FILE="/etc/modules-load.d/homecontrol-sim-can.conf"

install -m 0755 "/etc/homecontrol/02_SIM/setup_can.py" "${INSTALL_ROOT}/06_config/02_SIM/setup_can.py"

cat >"${MODULES_FILE}" <<'EOF'
can
can_raw
gs_usb
EOF

cat >/etc/systemd/system/${CAN_SERVICE} <<EOF
[Unit]
Description=HomeControl SIM CAN interface setup
After=systemd-modules-load.service network-online.target
Before=homecontrol-module@02_SIM.service

[Service]
Type=oneshot
WorkingDirectory=${INSTALL_ROOT}
Environment=PYTHONPATH=${INSTALL_ROOT}
ExecStart=${INSTALL_ROOT}/.venv/bin/python ${INSTALL_ROOT}/06_config/02_SIM/setup_can.py --apply
ExecStartPost=${INSTALL_ROOT}/.venv/bin/python ${INSTALL_ROOT}/06_config/02_SIM/setup_can.py --check
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${CAN_SERVICE}"

if [[ "${HC_SKIP_START:-0}" != "1" ]]; then
  systemctl restart "${CAN_SERVICE}"
fi
