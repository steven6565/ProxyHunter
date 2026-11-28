#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$DIR/server/server.pid" ] && kill -0 "$(cat "$DIR/server/server.pid")" 2>/dev/null; then
  echo "RUNNING (PID $(cat "$DIR/server/server.pid"))"
else
  echo "STOPPED"
fi
curl -s http://127.0.0.1:${PROXYHUNTER_PORT:-8000}/health || true