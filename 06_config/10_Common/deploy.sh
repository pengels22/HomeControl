#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_script_lib.sh"

PACKAGE="${1:-all}"
if [[ "${HC_RELEASE_SHA:-}" == "" ]]; then
  HC_RELEASE_SHA="$(git -C "$(hc_repo_root)" rev-parse HEAD)"
  export HC_RELEASE_SHA
fi

hc_print_plan "deploy" "$PACKAGE"
cd "$(hc_repo_root)"
python3 -m homecontrol_cli deploy --dry-run
