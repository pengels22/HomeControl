#!/usr/bin/env bash
set -euo pipefail
# Integration hook for the HCM updater. Intentionally does not alter firewall state yet.
# Replace with the site-specific Zyxel/API or local nftables action once that path is finalized.
action="${1:-}"
ip="${2:-}"
case "$action" in
  open|close) echo "[DRY RUN] $action update egress for $ip" ;;
  *) echo "usage: $0 {open|close} <module-ip>" >&2; exit 2 ;;
esac
