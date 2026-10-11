#!/usr/bin/env bash
set -euo pipefail

hc_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

hc_print_plan() {
  local action="$1"
  local package="$2"
  local release="${HC_RELEASE_SHA:-unresolved}"
  printf 'HomeControl %s plan\n' "$action"
  printf '  package: %s\n' "$package"
  printf '  release: %s\n' "$release"
  printf '  remote execution: disabled in source-tree foundation\n'
}
