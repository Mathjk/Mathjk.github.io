#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export MYWEB_APP_ROOT="/home/jk/myweb/myapp"

if command -v python3 >/dev/null 2>&1; then
  exec python3 local_app_server.py
fi

exec python local_app_server.py
