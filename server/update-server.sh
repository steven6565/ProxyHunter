#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
git pull --ff-only 2>/dev/null || true
source .venv/bin/activate 2>/dev/null || true
pip install -r server/requirements.txt
./server/stop-server.sh
./server/start-server.sh