#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate 2>/dev/null || true
pip install --upgrade pip
pip install -r server/requirements.txt
if [ ! -f .env ]; then
  API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > .env <<EOF
PROXYHUNTER_API_KEY=$API_KEY
PROXYHUNTER_DATA_DIR=$DIR/data
PROXYHUNTER_HOST=0.0.0.0
PROXYHUNTER_PORT=8000
EOF
  echo "Generated API key: $API_KEY"
fi
mkdir -p data exports output/logs
echo "Installation complete. Start with: ./server/start-server.sh"