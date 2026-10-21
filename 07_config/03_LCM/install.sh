#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_INSTALL="${SCRIPT_DIR}/../common/install_module.sh"

if [[ ! -x "$COMMON_INSTALL" ]]; then
  INSTALL_ROOT="${HC_INSTALL_ROOT:-/opt/HomeControl}"
  REPO_URL="${HC_REPO_URL:-https://github.com/pengels22/HomeControl.git}"
  BRANCH="${HC_BRANCH:-main}"
  RELEASE_SHA="${HC_RELEASE_SHA:-}"
  if [[ "${EUID}" -ne 0 ]]; then
    exec sudo --preserve-env=HC_INSTALL_ROOT,HC_REPO_URL,HC_BRANCH,HC_RELEASE_SHA,HC_SKIP_START bash "$0"
  fi
  if [[ -d "${INSTALL_ROOT}/.git" ]]; then
    if [[ -n "$RELEASE_SHA" ]]; then
      git -C "$INSTALL_ROOT" fetch origin
      git -C "$INSTALL_ROOT" checkout --detach "$RELEASE_SHA"
    else
      git -C "$INSTALL_ROOT" fetch origin "$BRANCH"
      git -C "$INSTALL_ROOT" checkout "$BRANCH"
      git -C "$INSTALL_ROOT" pull --ff-only origin "$BRANCH"
    fi
  else
    mkdir -p "$(dirname "$INSTALL_ROOT")"
    git clone "$REPO_URL" "$INSTALL_ROOT"
    if [[ -n "$RELEASE_SHA" ]]; then
      git -C "$INSTALL_ROOT" checkout --detach "$RELEASE_SHA"
    else
      git -C "$INSTALL_ROOT" checkout "$BRANCH"
    fi
  fi
  COMMON_INSTALL="${INSTALL_ROOT}/07_config/common/install_module.sh"
fi

exec "$COMMON_INSTALL" "03_LCM" "03_LCM" "lcm.yaml"
