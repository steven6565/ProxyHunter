#!/usr/bin/env bash
# ProxyHunter v4.0.0 backend installer.
#
# Tested on Debian/Ubuntu-style VPS images.  Also works in Daytona sandboxes
# (root user, no systemd) by falling back to a PID-managed background process.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "==> Installing system packages"
if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update -y
  $SUDO apt-get install -y python3 python3-venv python3-pip curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  $SUDO dnf install -y python3 python3-pip curl ca-certificates
elif command -v yum >/dev/null 2>&1; then
  $SUDO yum install -y python3 python3-pip curl ca-certificates
elif command -v apk >/dev/null 2>&1; then
  $SUDO apk add --no-cache python3 py3-pip curl ca-certificates
else
  echo "WARNING: no supported package manager found; ensure python3, venv and curl are installed." >&2
fi

echo "==> Creating virtual environment and installing Python dependencies"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r server/requirements.txt

echo "==> Preparing data directories"
mkdir -p data exports output/logs

if [ ! -f .env ]; then
  API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  PORT="${PROXYHUNTER_PORT:-8000}"
  cat > .env <<EOF
PROXYHUNTER_API_KEY=$API_KEY
PROXYHUNTER_DATA_DIR=$DIR/data
PROXYHUNTER_HOST=0.0.0.0
PROXYHUNTER_PORT=$PORT
PROXYHUNTER_GATEWAY_PORT=8080
EOF
  chmod 600 .env
  echo "==> Generated a new API key (stored in $DIR/.env)"
else
  echo "==> Reusing existing $DIR/.env"
fi

# shellcheck disable=SC1091
set -a; source .env; set +a
PORT="${PROXYHUNTER_PORT:-8000}"
API_KEY="${PROXYHUNTER_API_KEY:-}"

SERVICE_NAME="proxyhunter-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
USE_SYSTEMD="false"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  USE_SYSTEMD="true"
fi

if [ "$USE_SYSTEMD" = "true" ]; then
  echo "==> Installing systemd service"
  $SUDO tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=ProxyHunter v4.0.0 centralized backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/.venv/bin/python $DIR/server/main.py
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
  $SUDO systemctl restart "$SERVICE_NAME"
else
  echo "==> systemd not available; starting with the PID-managed launcher"
  ./server/start-server.sh
fi

echo "==> Waiting for the backend to become healthy"
HEALTHY="false"
for _ in $(seq 1 40); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    HEALTHY="true"
    break
  fi
  sleep 2
done
if [ "$HEALTHY" != "true" ]; then
  echo "ERROR: backend did not become healthy. Check ./server/logs-server.sh" >&2
  exit 1
fi

PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
HOSTNAME_VALUE="$(hostname 2>/dev/null || true)"

cat <<EOF

============================================================
 ProxyHunter v4.0.0 backend is running
============================================================
 Local health : http://127.0.0.1:${PORT}/health
 API base URL : http://${PUBLIC_IP:-$HOSTNAME_VALUE}:${PORT}
 API key      : ${API_KEY}

 Windows client (first launch):
   1. Enter the API base URL above.
   2. Enter the API key above.
   3. The client saves it securely and reconnects on every start.

 VPS / public server:
   - Open TCP ${PORT} in your firewall (or use the HTTPS reverse proxy below).
   - For production use HTTPS. Example with Caddy:
       sudo apt install -y caddy
       echo 'your-domain.example {
         reverse_proxy 127.0.0.1:${PORT}
       }' | sudo tee /etc/caddy/Caddyfile
       sudo systemctl reload caddy
     Then use https://your-domain.example in the Windows client.

 Daytona sandbox:
   - Run: daytona port forward ${PORT}
   - Use the HTTPS preview URL shown by Daytona as the API base URL.
   - Keep the sandbox running while the Windows client is connected.

 Management:
   ./server/start-server.sh
   ./server/stop-server.sh
   ./server/restart-server.sh
   ./server/status-server.sh
   ./server/logs-server.sh
   ./server/update-server.sh

 Security:
   - Never share the API key or commit .env.
   - The rotating gateway listens on 127.0.0.1:8080 on the server only.
============================================================
EOF
