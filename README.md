# ProxyHunter v3.1.2 — Desktop & Mobile Edition (packaged discovery fixes)

> **v3.0 adds a native Kotlin/Jetpack Compose Android app, a lightweight Tkinter Windows desktop app, a shared backend controller, an export engine, and reproducible APK/EXE build workflows.** The proven Python backend and all v2 features are preserved. The CLI remains available as an advanced mode: `python3 main.py`.
>
> **v3.1.0:** fixes the Android Find Proxies crash (missing `rich` in Chaquopy → bridge import failure → uncaught Kotlin coroutine exception), adds worker-selection dialog, automatic backend/gateway startup with independent Internet/Backend/Gateway statuses, and compact-layout fixes. See `TEST_REPORT.md` for root-cause evidence.
>
> **Build status:** v3.1 APK/EXE/Setup were rebuilt by GitHub Actions and verified as genuine files. Android is debug-signed; Windows binaries are unsigned. Physical-device and interactive GUI tests remain **NOT TESTED** in this environment.

## v3.0 frontends

### Android (`com.proxyhunter.app`, Android 8.0+)
- Five tabs: **Home, Proxies, Gateway, Downloads, Settings**.
- Premium dark theme (optional light), rounded cards, real statistics only.
- Foreground service with persistent notification and Stop action; Chaquopy hosts the shared Python backend.
- Searchable/filterable proxy browser with copy buttons; country selector with flags and validated counts; export/share to `Download/ProxyHunter/`.
- Minimal permissions: INTERNET, network state, foreground service + notifications. No root or broad storage permission.

### Windows 10/11 x64
- Lightweight Tkinter desktop app (no browser engine) with nine sidebar sections: Dashboard, Proxy Discovery, Proxy Checker, Proxy List, Rotating Gateway, Downloads, Activity Logs, Settings, About.
- Sortable multi-select proxy table, right-click copy, Ctrl+C/Ctrl+E shortcuts, background operations that never block the UI.
- System tray, optional Windows startup, native file dialogs, default exports to `%USERPROFILE%\Downloads\ProxyHunter\`.
- Packaging: PyInstaller portable EXE + Inno Setup installer with start-menu/desktop shortcuts and uninstall support.

### Project layout
```text
ProxyHunter/
├── backend/     shared controller + background worker
├── shared/      export engine (TXT/CSV/JSON, history, custom folders)
├── proxyhunter/ preserved discovery/checker/gateway/security engine
├── android/     Kotlin/Compose app + Chaquopy bridge
├── desktop/     Tkinter app + PyInstaller spec + installer script
├── assets/      original shield/nodes icon (ICO + vector drawable)
├── tests/       controlled test suite + TLS fixtures
├── builds/      Windows build script
└── .github/workflows/  reproducible Android/Windows builds
```

---

# Proxy Hunter v2.0 — Production Edition (baseline below)

**Automated proxy discovery, validation, management and rotating gateway** — a fast, configurable Python 3.11+ platform with a live Rich dashboard.

Proxy Hunter finds public proxies from GitHub repositories/raw lists, public proxy websites, JSON/TXT/CSV APIs and your own custom sources; validates them concurrently over HTTP, HTTPS, SOCKS4 and SOCKS5; enriches them with GeoIP data; keeps tidy output files; and exposes one stable local proxy endpoint that rotates only among recently validated upstreams.

> **Capacity is honest:** the dashboard reports eligible proxies and unique verified exit IPs. Public free-proxy availability is transient — no unlimited IPs or guaranteed uptime are advertised. When no eligible proxy exists for a selection, connections fail closed with HTTP 502.

> **Legal & ethical use.** Only use sources that permit automated access and respect their published rate limits. Never send passwords, cookies, tokens or other sensitive data through public proxies. Do not attempt to bypass authentication, CAPTCHAs or access restrictions. This tool is for legitimate security research, testing and network engineering.

---

## Features

- **Discovery** — bounded-concurrency async fetchers for raw GitHub lists, GitHub repository search, HTML tables, plain text, JSON APIs and custom sources; per-source error logs.
- **Four protocols** — HTTP, HTTPS (HTTP CONNECT), SOCKS4 and SOCKS5, auto-detected from source data.
- **Fast checker** — asyncio + aiohttp with a token-bucket rate limiter, bounded semaphore, configurable workers, retries and timeouts. Presets: 10 / 50 / 100 / 200 / 500 workers or a custom count.
- **Rich metadata** — address, protocol, status, response time, country, ISO code, city, ISP and last-checked time; only working proxies are stored.
- **GeoIP-first** — optional local MaxMind `GeoLite2-City.mmdb` lookups; ip-api.com batch fallback (100 IPs/request, rate limited) and geo included free from ip-api validation responses.
- **Country management** — dedicated files for US, GB (United Kingdom), IN, DE, CA, FR, JP, SG, NL and AU, per-country files for every other detected code, plus `other_countries.txt`; filters accept any ISO code.
- **Live dashboard** — animated progress, discovered/unique/working/dead counters, checks-per-second, active workers, country distribution, average latency, CPU/RAM, elapsed time and a rolling activity log.
- **Rotating proxy gateway v2** — one stable local endpoint (`http://127.0.0.1:8080` by default); rotates per connection among eligible, validated upstreams; HTTP/CONNECT/SOCKS4/SOCKS5; six modes (per connection, round robin, random, time based, sticky, lowest latency); multi-country selection; circuit breakers with exponential backoff; quarantine and recovery; global/per-user concurrency caps; fail-closed errors.
- **Secure remote access** — localhost by default; PBKDF2-SHA256 credentials, optional TLS, IP allowlists, destination policies, session tokens, rate limits and auth-failure logs for authorized VPS deployments.
- **Health lifecycle** — last-success timestamps, consecutive failure counts, response latency tracking, temporary quarantine, controlled revalidation, recovery, expiry of stale validation results and duplicate detection.
- **Ten-option interactive menu** (including the gateway submenu) plus non-interactive CLI flags for scripting.
- **Automatic refresh** — 5/15/30/60-minute or custom intervals; discovers, revalidates, drops expired entries and rewrites all files.
- **Safe & reliable** — rejects private/loopback/reserved/link-local addresses, DNS-pins hostnames to public IPs, graceful shutdown, incremental persistence so results survive interruption, atomic file writes.
- **Cross-platform** — Android/Termux, Ubuntu/Debian, Linux VPS and Windows 10/11; `/proc` fallback when `psutil` is unavailable.

---

## Installation

### Quick start (any platform)

```bash
cd ProxyHunter
python3 main.py          # missing dependencies are installed automatically
```

### Android / Termux

```bash
pkg update && pkg install python git
git clone <this-repo> ProxyHunter
cd ProxyHunter
bash install.sh
.venv/bin/python main.py
```

`psutil` cannot be compiled on Android, so Proxy Hunter reads `/proc/stat` and `/proc/meminfo` instead — no extra setup needed.

### Ubuntu / Debian

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
git clone <this-repo> ProxyHunter
cd ProxyHunter
bash install.sh
.venv/bin/python main.py
```

### Linux VPS

Same as Ubuntu. For high worker counts, raise the file-descriptor limit first:

```bash
ulimit -n 4096
```

Presets above 100 workers also benefit from `sysctl -w net.ipv4.ip_local_port_range="1024 65535"`.

### Windows 10/11

Install Python 3.11+ from [python.org](https://www.python.org/downloads/) (tick **Add Python to PATH**), then in PowerShell/CMD:

```bat
cd ProxyHunter
install.bat
.venv\Scripts\python.exe main.py
```

---

## Usage

### Interactive menu

```text
[1] Discover Public Proxies
[2] Check Existing Proxy List
[3] Discover and Validate Automatically
[4] Filter Proxies by Country
[5] Filter Proxies by Protocol
[6] Export Working Proxies
[7] Configure Workers and Timeout
[8] Recheck Saved Proxies
[9] Automatic Refresh Mode
[0] Exit
```

Press `Ctrl+C` at any time: in-flight checks finish, validated results are flushed to SQLite and the app exits cleanly.

### Command line

```bash
python3 main.py --discover                 # discovery only
python3 main.py --check output/discovered_proxies.txt
python3 main.py --auto --workers 100 --timeout 6
python3 main.py --export                   # rewrite outputs from the database
python3 main.py --gateway                  # start the rotating gateway (Ctrl+C to stop)
```

### Rotating proxy gateway

From the main menu press **G**. The gateway submenu offers:

```text
[1] Start   [2] Stop   [3] Restart
[4] Countries   [5] Rotation   [6] Settings   [7] Live monitor
[8] Health now   [9] Refresh now   [0] Back
```

- **Endpoint:** applications use one address, e.g. `http://127.0.0.1:8080`; no per-app proxy changes are needed. Upstream selection happens for each *new* client connection, so existing connections keep working until they finish.
- **Countries:** All, US, GB, IN, DE, CA, or a comma-separated list of ISO codes (e.g. `US,GB,IN`). Country is verified from the **actual exit IP**; the menu shows recent validated counts per country and warns when a selection has no eligible proxies. If no healthy proxy matches, requests get `502 Bad gateway` — the gateway keeps running and never uses your direct IP.
- **Rotation modes:** `per_connection` (default), `time_based` (every N seconds), `round_robin`, `random`, `sticky`, `lowest_latency`. Consecutive reuse of the same IP is avoided whenever alternatives exist (except in sticky/time-based/lowest-latency modes, where selection is intentional).
- **Pool:** all recently verified proxies from `output/proxies.db` are imported automatically — no hardcoded pool cap. Health checks run every 5 minutes, pool discovery/refresh every 15 minutes (both configurable); failed proxies are quarantined, revalidated in a bounded batch and recovered when healthy again; stale validation expires from exports.
- **v2 dashboard:** online/offline status, endpoint, selected country, rotation mode, eligible/total proxies, unique verified exit IPs, active connections, successful/failed requests, average latency, health distribution, CPU/RAM, last refresh/health, application uptime, version and capacity warnings.
- **Settings:** bind address, port, retries, timeouts, destination/IP policies, connection limits, refresh/health intervals, rotation window, TLS and authentication.

**Security:** the gateway binds to `127.0.0.1` and needs no credentials by default. Remote binding requires a username/password (**stored as PBKDF2-SHA256 salted hashes**), `allow_remote_access: true`, and ideally TLS plus an IP allowlist; otherwise startup is refused. Auth failures are logged to `output/logs/gateway_auth.log`. Never expose an unauthenticated proxy server. Use the gateway only for authorized testing; respect destination rate limits and access controls. See `PRODUCTION_READINESS.md` for the VPS checklist.

**Verified behaviour (v2.0):** 30/30 mandatory controlled tests passed. The same endpoint produced **3 distinct controlled exit IPs across 9 connections** and **7 distinct live exit IPs across 8 authorized live connections**; country filtering matched exit-IP geography; dead upstreams were quarantined and later recovered; empty pools and timeouts failed closed with 502; auth returned 407 without credentials and 200 with valid ones; 500 concurrent local requests were handled without crashes or leaks. TLS listener testing is **BLOCKED** locally (no certificate tooling). Full evidence: `TEST_REPORT.md`.

---

## Configuration (`config.json`)

| Key | Default | Meaning |
|---|---|---|
| `workers.preset` | `normal` | `low`(10), `normal`(50), `fast`(100), `high`(200), `advanced`(500), `custom` |
| `workers.count` | `50` | Effective concurrency (1–2000); bounded by a semaphore |
| `timeout_seconds` | `8` | Total timeout for each validation request |
| `connect_timeout_seconds` | `5` | Connection timeout |
| `retries` | `1` | Extra attempts with a different endpoint on failure |
| `rate_limit_per_second` | `15` | Global token bucket for validation requests (`0` = unlimited) |
| `discovery_concurrency` | `10` | Simultaneous source fetches |
| `validation_endpoints` | ip-api, ipify, httpbin | Weighted endpoints; each must return the exit IP |
| `export_format` | `ip_port` | `ip_port` (`1.2.3.4:8080`) or `protocol_url` (`http://1.2.3.4:8080`) — both variants are always written |
| `protocol_filter` | all four | Protocols to discover/validate |
| `country_filter` | `[]` | ISO codes to restrict validation (`GB` for the UK); empty = all |
| `max_proxies_to_check` | `0` | Cap per run (`0` = unlimited) |
| `use_remote_geo` | `true` | Allow the ip-api.com batch fallback |
| `geoip_db_path` | `""` | Path to a MaxMind `GeoLite2-City.mmdb` |
| `refresh_mode` | 15 min | Interval, auto-discover/recheck, expiry in hours |
| `github_token` | `""` | Optional token to raise GitHub's API rate limit |
| `validation_max_age_hours` | `24` | Validation results older than this are excluded from exports and gateway selection |
| `gateway.bind` / `gateway.port` | `127.0.0.1` / `8080` | Stable endpoint; remote bind needs auth + `allow_remote_access` |
| `gateway.rotation_mode` | `per_connection` | Also `round_robin`, `random`, `time_based`, `sticky`, `lowest_latency` |
| `gateway.pool_refresh_minutes` | `15` | Background discovery/validation refresh (v1's 1440 is migrated to 15) |
| `gateway.health_check_minutes` | `5` | Quarantine/recovery revalidation cycle |
| `gateway.health` | see config | Quarantine time, failure threshold, circuit breaker/backoff, max upstream age |
| `gateway.security` | see config | IP allowlist, destination policy, connection/rate limits, TLS |
| `gateway.auth` | disabled | PBKDF2 username/hash/salt; plaintext passwords are migrated away |

### Sources (`sources.json`)

Sources are grouped by `github_raw`, `github_api`, `apis`, `websites` and `custom`. Each entry has a `name`, `type` (`raw`, `text`, `html`, `json`, `github_search`), a `url` (or `query` for search), `default_protocol` and `enabled`. JSON sources may set `json_path` (e.g. `proxies`) to select a nested list.

Add your own source in the `custom` array:

```json
{
  "name": "my-list",
  "type": "raw",
  "url": "https://example.org/proxies.txt",
  "default_protocol": "http",
  "enabled": true
}
```

Or call `Discovery.add_source({...})` from Python. Failures never stop a run: each source gets its own file in `output/logs/<name>.log` and a row in `source_errors` in SQLite.

### Offline GeoIP (recommended for large runs)

1. Create a free MaxMind account and download `GeoLite2-City.mmdb`.
2. Place it at `data/GeoLite2-City.mmdb`, or set `geoip_db_path` in `config.json`.
3. Restart Proxy Hunter — the dashboard shows the active backend.

Without a database, geography comes from the ip-api validation response or a rate-limited batch request, and is cached in SQLite.

---

## Output structure

```text
ProxyHunter/
├── output/
│   ├── working_proxies.txt              # configured export format
│   ├── working_proxies_addresses.txt    # the other format
│   ├── working_proxies.json             # full metadata
│   ├── working_proxies.csv
│   ├── discovered_proxies.txt           # raw unique candidates
│   ├── proxies.db                       # SQLite: working, history, source errors, geo cache
│   ├── protocols/{http,https,socks4,socks5}.txt
│   ├── countries/{US,GB,IN,DE,CA,FR,JP,SG,NL,AU}.txt
│   ├── countries/<other detected code>.txt
│   ├── countries/other_countries.txt
│   ├── filters/                         # ad-hoc country/protocol exports
│   └── logs/                            # per-source error logs
├── config.json
├── sources.json
├── requirements.txt
├── main.py
├── install.sh
├── install.bat
└── README.md
```

Files are written atomically (temporary file + rename) so readers never see partial data.

---

## Performance notes

- **Mobile / low RAM:** preset `low` (10 workers), timeout 5–6 s, rate limit 5–10/s.
- **VPS:** preset `high` or `advanced`; raise `ulimit -n`; keep rate limits respectful of the validation endpoints.
- GeoIP lookups are cached in memory and SQLite; the batch fallback uses at most 100 IPs per request and never faster than ~1.4 s between requests.
- SQLite uses WAL + `synchronous=NORMAL`, and results are committed in batches of 25 plus a final flush on interrupt.

---

## Architecture

| Module | Responsibility |
|---|---|
| `main.py` | Entry point, CLI flags, interactive menu, graceful shutdown |
| `bootstrap.py` | Automatic dependency installation |
| `proxyhunter/config.py` | Defaults, merging, validation, presets |
| `proxyhunter/discovery.py` | Async source fetching and parsing (text/HTML/JSON/GitHub) |
| `proxyhunter/gateway.py` | Rotating local HTTP/CONNECT gateway, pool management, health monitoring |
| `proxyhunter/checker.py` | Async validation engine, rate limiter, protocol transports |
| `proxyhunter/geo.py` | Local GeoIP + rate-limited batch fallback |
| `proxyhunter/storage.py` | SQLite schema, incremental writes, all exports |
| `proxyhunter/dashboard.py` | Rich live dashboard and metrics |
| `proxyhunter/resources.py` | CPU/RAM sampling (psutil or `/proc`) |
| `proxyhunter/utils.py` | Safe parsing, IP filtering, de-duplication |
| `proxyhunter/models.py` | `Proxy` data model |
| `proxyhunter/security.py` | PBKDF2 credentials, sessions, allowlists, destination policies, rate limits |
| `proxyhunter/logging_utils.py` | Size-rotating source/auth/access logs |
| `tests/test_suite.py` | 30 mandatory controlled tests + TLS status check |

---

## Production documentation

- `CHANGELOG.md` — v1.0 → v2.0 changes.
- `TEST_REPORT.md` — actual test results, controlled benchmarks and live rotation evidence.
- `PRODUCTION_READINESS.md` — verdict, security assessment and VPS deployment checklist.
- `output/test_results.json` — machine-readable test results.
- `output/live_rotation_result.json` — authorized live rotation evidence.

Full backup of v1.0 is preserved at `ProxyHunter_v1.0_backup` (project folder).

---

## Troubleshooting

- **No proxies found** — a source may be temporarily down; check `output/logs/` and the source's `enabled` flag. GitHub rate limits (403) are logged; add `github_token`.
- **Everything is dead** — free proxies have short lifetimes; reduce timeout, try SOCKS sources, or lower concurrency to avoid source-side throttling.
- **`psutil` install fails on Android** — expected; the `/proc` fallback is automatic. Leave it commented out in `requirements.txt`.
- **Windows signal handling** — `Ctrl+C` still stops the run; pending checks are cancelled and saved results are preserved.
