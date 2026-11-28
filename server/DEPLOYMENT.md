# ProxyHunter v4.0.0 — Backend Deployment

The Windows EXE is a lightweight client. Discovery, validation, storage and
exports run on this Linux backend. The client stores only the backend URL and
API key (DPAPI-protected on Windows) and reconnects automatically.

> **Status:** the code paths below are covered by automated tests and the
> packaged-EXE smoke test. A real VPS/Daytona deployment and Winlator/Wine run
> require credentials/hardware that were not available, so those two runtime
> environments are **not yet verified**.

## 1. Standard VPS (Ubuntu/Debian)

Requirements: 64-bit Linux, Python 3.10+, 1 CPU / 1 GB RAM minimum
(the reference target is 4 vCPU / 8 GB RAM).

```bash
sudo apt-get update -y
sudo apt-get install -y git curl
git clone https://github.com/steven6565/ProxyHunter.git
cd ProxyHunter
sudo bash server/install-server.sh
```

The installer:

- installs `python3`, `venv`, `pip`, `curl` and CA certificates;
- creates `.venv` and installs `server/requirements.txt`;
- creates the SQLite data directory (`data/`) and export directory (`exports/`);
- generates a cryptographically random API key and writes `.env` with mode `600`;
- installs and starts a systemd service (`proxyhunter-backend`);
- waits for `/health` and prints the API URL, API key and client instructions.

Save the printed API key. It is also in `.env`:

```bash
grep PROXYHUNTER_API_KEY .env
```

Open the API port only if you are not using an HTTPS reverse proxy:

```bash
sudo ufw allow 8000/tcp
```

### HTTPS reverse proxy (recommended)

```bash
sudo apt-get install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

Use `https://api.example.com` in the Windows client. Do not expose the API key
over plain HTTP on the public internet.

## 2. Daytona sandbox

```bash
# Inside the Daytona sandbox terminal
git clone https://github.com/steven6565/ProxyHunter.git
cd ProxyHunter
bash server/install-server.sh
```

Daytona has no systemd, so the installer falls back to the PID-managed
launcher. Forward the API port and copy the HTTPS preview URL:

```bash
daytona port forward 8000
```

In the Daytona dashboard, open the forwarded port and copy the `https://...`
preview URL. Enter that URL and the printed API key in the Windows client.
Keep the sandbox running while the client is connected.

## 3. Windows client first launch

1. Start `ProxyHunter_v4.0.0_Windows.exe` (or the Setup version).
2. Enter the backend HTTPS URL, for example `https://api.example.com`.
3. Enter the API key printed by the installer.
4. Click OK. The connection is saved to
   `%APPDATA%\ProxyHunter\connection.json` and reused on every start.
   On Windows the key is encrypted with DPAPI; on Wine/Winlator it falls back
   to an owner-only file.
5. Dashboard → **Find Proxies** starts discovery on the server.
   **Download Proxies** downloads the server-generated export.

The internal gateway URL/port is hidden from the dashboard; it is available
under **Settings → Advanced Diagnostics**.

## 4. Management commands

Run these from the repository root on the server:

```bash
./server/start-server.sh      # start (systemd or nohup fallback)
./server/stop-server.sh       # stop
./server/restart-server.sh    # restart
./server/status-server.sh     # service state + /health
./server/logs-server.sh       # follow logs
./server/update-server.sh     # git pull + pip install + restart
```

With systemd you can also use:

```bash
sudo systemctl status proxyhunter-backend
sudo systemctl restart proxyhunter-backend
sudo journalctl -u proxyhunter-backend -f
```

## 5. Configuration

`.env` (never commit this file):

```dotenv
PROXYHUNTER_API_KEY=<generated>
PROXYHUNTER_DATA_DIR=/opt/ProxyHunter/data
PROXYHUNTER_HOST=0.0.0.0
PROXYHUNTER_PORT=8000
PROXYHUNTER_GATEWAY_PORT=8080
```

- `PROXYHUNTER_DATA_DIR` holds the SQLite database, logs and exports.
- `PROXYHUNTER_GATEWAY_PORT` is the server-local rotating gateway. It is not
  exposed to the Windows client.
- To rotate the API key: edit `.env`, then
  `./server/restart-server.sh`, then re-enter the key in the client.

## 6. Verification commands

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -H "X-API-Key: $PROXYHUNTER_API_KEY" http://127.0.0.1:8000/api/stats
curl -fsS -H "X-API-Key: $PROXYHUNTER_API_KEY" http://127.0.0.1:8000/api/sources
```

The Windows CI job also starts this backend, runs the packaged
`ProxyHunter.exe --selftest`, and requires real discovery, three export
formats, JSON/CSV/TXT verification and an ONLINE gateway before publishing.

## 7. Troubleshooting

- **401 invalid api key** — the client key and `.env` do not match. Re-copy the
  key and restart the client (or edit the connection in `%APPDATA%`).
- **Backend did not become healthy** — run `./server/logs-server.sh`; check
  Python version and that port 8000 is free.
- **Daytona URL changes** — re-enter the new preview URL in the client. The
  API key can stay the same.
- **Gateway OFFLINE** — the gateway needs validated upstreams. Run discovery
  and validation first; check `Advanced Diagnostics`.
- **Update downloaded but not installed** — click **Restart and Update**.
  The helper waits for the old process to exit, replaces the EXE, verifies the
  version and rolls back if the new build does not start.
