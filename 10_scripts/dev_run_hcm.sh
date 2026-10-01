#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD:$PWD/01_HCM"
exec uvicorn hcm.main:app --app-dir 01_HCM --host 127.0.0.1 --port 8080 --reload
