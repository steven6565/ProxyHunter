#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [ -f "$SERVICE_FILE" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  journalctl -u "$SERVICE_NAME" -n 100 -f
else
  touch server/server.log
  tail -n 100 -f server/server.log
fi
