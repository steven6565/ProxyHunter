#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PORT="${PROXYHUNTER_PORT:-8000}"
# shellcheck disable=SC1091
set -a; source .env 2>/dev/null || true; set +a
PORT="${PROXYHUNTER_PORT:-$PORT}"

if [ -f "$SERVICE_FILE" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl --no-pager --lines=0 status "$SERVICE_NAME" || true
elif [ -f server/server.pid ] && kill -0 "$(cat server/server.pid)" 2>/dev/null; then
  echo "RUNNING (PID $(cat server/server.pid))"
else
  echo "STOPPED"
fi

echo -n "Health: "
curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" || echo "unavailable"
echo
