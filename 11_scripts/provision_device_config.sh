#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  provision_device_config.sh <device-type> <user@host> [remote-dir]

Device types:
  HCM, LCM, RCM, PNL, CONFLICT, LAB

Examples:
  11_scripts/provision_device_config.sh RCM orangepi@192.168.20.20
  11_scripts/provision_device_config.sh LCM root@192.168.20.30 /tmp/homecontrol-install

Environment passed to remote installer:
  HC_REPO_URL, HC_RELEASE_SHA, HC_BRANCH, HC_INSTALL_ROOT, HC_SKIP_START
USAGE
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 64
fi

DEVICE_TYPE="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
TARGET="$2"
REMOTE_DIR="${3:-/tmp/homecontrol-install}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$DEVICE_TYPE" in
  HCM) CONFIG_DIR="01_HCM" ;;
  LCM) CONFIG_DIR="03_LCM" ;;
  RCM) CONFIG_DIR="04_RCM" ;;
  PNL) CONFIG_DIR="05_PNL" ;;
  CONFLICT) CONFIG_DIR="07_CONFLICT" ;;
  LAB) CONFIG_DIR="08_LAB" ;;
  *)
    echo "Unknown device type: ${DEVICE_TYPE}" >&2
    usage
    exit 64
    ;;
esac

ssh "$TARGET" "rm -rf '$REMOTE_DIR' && mkdir -p '$REMOTE_DIR/07_config'"
scp -r "${REPO_ROOT}/07_config/common" "$TARGET:${REMOTE_DIR}/07_config/"
scp -r "${REPO_ROOT}/07_config/10_Common" "$TARGET:${REMOTE_DIR}/07_config/"
scp -r "${REPO_ROOT}/07_config/${CONFIG_DIR}" "$TARGET:${REMOTE_DIR}/07_config/"

REMOTE_ENV=()
for name in HC_REPO_URL HC_RELEASE_SHA HC_BRANCH HC_INSTALL_ROOT HC_SKIP_START; do
  if [[ -n "${!name:-}" ]]; then
    REMOTE_ENV+=("${name}=${!name}")
  fi
done

printf -v ENV_PREFIX '%q ' "${REMOTE_ENV[@]}"
ssh "$TARGET" "cd '$REMOTE_DIR/07_config/${CONFIG_DIR}' && ${ENV_PREFIX}bash ./install.sh"
