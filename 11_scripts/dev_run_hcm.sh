#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
export HCM_DEV_MODE=true
exec uvicorn 01_HCM.main:app --host 127.0.0.1 --port 8080 --reload
