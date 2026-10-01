#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${HC_INSTALL_ROOT:-/opt/HomeControl}"
REPO_URL="${HC_REPO_URL:-https://github.com/pengels22/HomeControl.git}"
BRANCH="${HC_BRANCH:-main}"
SERVICE_NAME="homecontrol-hcm.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-running HCM installer with sudo..."
  exec sudo --preserve-env=HC_INSTALL_ROOT,HC_REPO_URL,HC_BRANCH,HC_SKIP_START bash "$0"
fi

if [[ -d "${INSTALL_ROOT}/.git" ]]; then
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

mkdir -p "${INSTALL_ROOT}/06_config/01_HCM" "/etc/homecontrol/01_HCM" "${INSTALL_ROOT}/runtime"
cp -a "${SCRIPT_DIR}/." "/etc/homecontrol/01_HCM/"
cp -a "${SCRIPT_DIR}/." "${INSTALL_ROOT}/06_config/01_HCM/"

install -m 0644 "${INSTALL_ROOT}/07_servises/systemd/homecontrol-hcm.service" \
  "/etc/systemd/system/${SERVICE_NAME}"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

if [[ "${HC_SKIP_START:-0}" != "1" ]]; then
  systemctl restart "$SERVICE_NAME"
fi

echo "Installed HCM into ${INSTALL_ROOT}"
