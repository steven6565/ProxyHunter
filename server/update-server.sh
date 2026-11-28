#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
source .venv/bin/activate 2>/dev/null || true

echo "==> Pulling latest source"
git pull --ff-only
echo "==> Updating Python dependencies"
python -m pip install --upgrade -r server/requirements.txt
echo "==> Restarting backend"
./server/restart-server.sh
echo "==> Status"
./server/status-server.sh
