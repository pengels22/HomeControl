#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_script_lib.sh"
PACKAGE="${1:-all}"
hc_print_plan "rollback" "$PACKAGE"
printf '  status: MANUAL INTERVENTION REQUIRED for live hosts\n'
