#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [ -f "$SERVICE_FILE" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  $SUDO systemctl stop "$SERVICE_NAME"
  echo "Stopped $SERVICE_NAME (systemd)"
  exit 0
fi

if [ -f server/server.pid ]; then
  PID="$(cat server/server.pid)"
  kill "$PID" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$PID" 2>/dev/null; then break; fi
    sleep 0.5
  done
  kill -9 "$PID" 2>/dev/null || true
  rm -f server/server.pid
  echo "Stopped"
else
  echo "Not running"
fi
