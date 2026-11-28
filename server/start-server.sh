#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
source .venv/bin/activate 2>/dev/null || true
set -a; source .env 2>/dev/null || true; set +a
nohup python3 server/main.py > server/server.log 2>&1 &
echo $! > server/server.pid
echo "Started ProxyHunter backend (PID $(cat server/server.pid))"