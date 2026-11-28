#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$DIR/server/server.pid" ]; then
  kill "$(cat "$DIR/server/server.pid")" 2>/dev/null || true
  rm -f "$DIR/server/server.pid"
  echo "Stopped"
else
  echo "Not running"
fi