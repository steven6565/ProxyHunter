#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [ -f "$SERVICE_FILE" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  $SUDO systemctl start "$SERVICE_NAME"
  echo "Started $SERVICE_NAME (systemd)"
  exit 0
fi

if [ -f server/server.pid ] && kill -0 "$(cat server/server.pid)" 2>/dev/null; then
  echo "Already running (PID $(cat server/server.pid))"
  exit 0
fi
# shellcheck disable=SC1091
set -a; source .env 2>/dev/null || true; set +a
source .venv/bin/activate 2>/dev/null || true
nohup python3 server/main.py > server/server.log 2>&1 &
echo $! > server/server.pid
echo "Started ProxyHunter backend (PID $(cat server/server.pid))"
