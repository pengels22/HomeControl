#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install_module.sh <module-dir> <module-service-id> <config-file>

Environment:
  HC_INSTALL_ROOT   Target repo path. Default: /opt/HomeControl
  HC_REPO_URL       Git source if the repo is not already present.
  HC_SOURCE_REPO    Optional existing repo path to copy from instead of git clone.
  HC_BRANCH         Git branch to checkout/pull. Default: main
  HC_SKIP_START     Set to 1 to install without starting services.
USAGE
}

if [[ $# -ne 3 ]]; then
  usage
  exit 64
fi

MODULE_DIR="$1"
MODULE_SERVICE_ID="$2"
CONFIG_FILE="$3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_ROOT="${HC_INSTALL_ROOT:-/opt/HomeControl}"
REPO_URL="${HC_REPO_URL:-https://github.com/pengels22/HomeControl.git}"
BRANCH="${HC_BRANCH:-main}"
SERVICE_NAME="homecontrol-module@${MODULE_SERVICE_ID}.service"
UPDATE_SERVICE_NAME="homecontrol-update.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-running installer with sudo..."
  exec sudo --preserve-env=HC_INSTALL_ROOT,HC_REPO_URL,HC_SOURCE_REPO,HC_BRANCH,HC_SKIP_START \
    bash "$0" "$MODULE_DIR" "$MODULE_SERVICE_ID" "$CONFIG_FILE"
fi

if [[ -n "${HC_SOURCE_REPO:-}" ]]; then
  mkdir -p "$INSTALL_ROOT"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    "${HC_SOURCE_REPO%/}/" "$INSTALL_ROOT/"
elif [[ -d "${INSTALL_ROOT}/.git" ]]; then
  git -C "$INSTALL_ROOT" fetch origin "$BRANCH"
  git -C "$INSTALL_ROOT" checkout "$BRANCH"
  git -C "$INSTALL_ROOT" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$INSTALL_ROOT")"
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_ROOT"
fi

python3 -m venv "${INSTALL_ROOT}/.venv"
"${INSTALL_ROOT}/.venv/bin/python" -m pip install --upgrade pip
"${INSTALL_ROOT}/.venv/bin/python" -m pip install -r "${INSTALL_ROOT}/requirements.txt"

mkdir -p "${INSTALL_ROOT}/06_config/${MODULE_DIR}" "/etc/homecontrol/${MODULE_DIR}" "${INSTALL_ROOT}/runtime"
cp -a "${CONFIG_DIR}/." "/etc/homecontrol/${MODULE_DIR}/"
cp -a "${CONFIG_DIR}/." "${INSTALL_ROOT}/06_config/${MODULE_DIR}/"

install -m 0644 "${INSTALL_ROOT}/07_servises/systemd/homecontrol-module@.service" \
  /etc/systemd/system/homecontrol-module@.service

if [[ -x "/etc/homecontrol/${MODULE_DIR}/post_install.sh" ]]; then
  HC_INSTALL_ROOT="$INSTALL_ROOT" "/etc/homecontrol/${MODULE_DIR}/post_install.sh"
fi

cat >/etc/systemd/system/${UPDATE_SERVICE_NAME} <<EOF
[Unit]
Description=HomeControl module update service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_ROOT}
Environment=PYTHONPATH=${INSTALL_ROOT}
ExecStart=${INSTALL_ROOT}/.venv/bin/python ${INSTALL_ROOT}/07_servises/update_service.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" "$UPDATE_SERVICE_NAME"

if [[ "${HC_SKIP_START:-0}" != "1" ]]; then
  systemctl restart "$SERVICE_NAME" "$UPDATE_SERVICE_NAME"
fi

echo "Installed ${MODULE_SERVICE_ID} from ${CONFIG_FILE} into ${INSTALL_ROOT}"
