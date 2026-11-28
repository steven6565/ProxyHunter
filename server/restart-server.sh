#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [ -f "$SERVICE_FILE" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  $SUDO systemctl restart "$SERVICE_NAME"
  echo "Restarted $SERVICE_NAME (systemd)"
  exit 0
fi

./server/stop-server.sh
./server/start-server.sh
