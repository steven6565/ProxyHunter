# Changelog

## v4.0.0 — Centralized backend + lightweight Windows client (2026-11-28)

### Architecture
- New Linux backend (`server/`, FastAPI) wrapping the proven `BackendController`/`BackendWorker`. One-command installer `sudo bash server/install-server.sh` (systemd + Daytona/nohup fallback, random API key, `.env` 0600, health check) and `server/DEPLOYMENT.md` (VPS, Caddy HTTPS, Daytona port-forwarding, management commands).
- Windows EXE is a thin `RemoteBackendController`/`RemoteBackendWorker` HTTP client; no local discovery/validation/export. Connection remembered at `%APPDATA%\ProxyHunter\connection.json`, API key protected with Windows DPAPI (owner-only fallback for Wine/Winlator); first-launch setup asks once; future updates preserve it.
- Backend endpoints: `/health`, `/api/stats`, `/api/discover`, `/api/check`, `/api/refresh`, `/api/stop`, `/api/proxies` (working_only + limit), `/api/sources`, `/api/source_set`, `/api/source_test`, `/api/export` (txt/csv/json, working_only), `/api/download/{name}`, `/api/gateway_start|stop|restart`, `/api/gateway_countries`, `/api/gateway_mode`, `/api/gateway_auth`, `/api/countries`, `/api/capacity`, `/api/rotation_modes`, `/api/worker_presets`, `/api/events`, `/api/connectivity`, `/ws` (query-key or first-message auth). API key via `X-API-Key`.
- `Storage.get_all()` added for all-proxy export; `working_only:false` exports every stored/discovered proxy; exports always written to the fixed data directory and downloaded to the client.
- Internal gateway URL/ports hidden from the dashboard; available only in Settings → Advanced Diagnostics. No fake progress.

### Selftest
- `selftest_mode.py` (stdlib-only) dispatched at the top of `desktop/app.py`, before Tkinter/GUI/single-instance/updater; `--selftest` and `PROXYHUNTER_SELFTEST=1`; `PROXYHUNTER_BACKEND_URL`/`PROXYHUNTER_API_KEY`; 165s watchdog; `os._exit`; always writes `selftest.json` + `selftest.log`.
- Verifies real backend health, auth rejects a wrong key, saved connection round-trip, source configuration, real discovery, validation trigger, three export formats downloaded, JSON `total` == `proxies` length > 0, CSV header + rows, non-empty TXT, ONLINE gateway, packaged `sources.json`/`config.json`, countries/capacity/rotation modes; exit 0 only on `ok:true`.
- CI starts `server/main.py` on 127.0.0.1:8000 with key `testkey`, builds the packaged EXE, runs a **bounded** `WaitForExit` (max 180s; 210s harness) with log/crash capture and always-cleans-up backend; asserts all fields; 5-minute step, 20-minute job.

### Updater
- Verified flow: download → verify HMAC-SHA256 manifest (or published `SHA256SUMS.txt`) → verify SHA-256 of the artifact → `ProxyHunterUpdater.exe` helper → graceful close → wait for process exit/unlock → replace → relaunch → verify reported version → rollback restore on any failure; corrupt/truncated replacements rejected via PE pre-check; new **Restart and Update**; never stuck at “Installing on Exit”; no `os.kill(pid, 0)` (Windows-safe `OpenProcess`, shell `kill -0` only on Linux); `updater.log`; update preserves `connection.json`.
- CI updater test: replace + version + relaunch, corrupt pre-check, real rollback with a valid-but-wrong EXE.

### Tests (evidence)
- 34/34 `python3 tests/test_suite.py` PASS (added `34_update_manifest_verification`); `python3 -m compileall` clean.
- GitHub Actions Windows CI `build-windows.yml` PASS (final run **46180193060**).
- Packaged EXE selftest on clean Windows Server 2022: `ok:true`, 19 sources / 16 enabled, `discovered=42585`, `export_total=17752`, `json_verified/csv_verified/txt_verified=true`, `gateway_ok=true`, `auth_ok=true`, `connection_saved=true`, `resources_ok=true`, `duration≈7.6s`.
- Updater replace / version / rollback smoke test PASS.
- **NOT TESTED:** real VPS/Daytona deployment and HTTPS reverse proxy, Winlator/Wine runtime, physical Android device (out of scope). No claim of these is made.
- Android app intentionally unchanged. No signing key is committed; artifacts are unsigned unless a signing certificate secret is configured.

## v3.1.2 — Packaged discovery, TLS trust store and source seeding (2026-11-27)

### Windows
- Fixed the packaged discovery root cause: `ensure_packaged_defaults()` now seeds the full 19 authorized sources when `sources.json` is missing/empty, and `load_sources()` re-seeds empty/malformed/outdated files instead of accepting `{"custom": []}`.
- `base_dir()` now honors `PROXYHUNTER_HOME` (Android filesDir) even on development machines.
- Packaged TLS trust store: added `proxyhunter/net.py` (`configure_ca_bundle()` + `make_ssl_context()`); certifi is added to requirements and collected into the onefile EXE, so aiohttp uses the bundled CA bundle on Windows and Android.
- Discovery progress no longer shows "complete" when zero proxies were found; worker selection and live stats preserved.
- Clean-directory Windows smoke test passes with real discovery: 16/19 sources enabled, 18,217 proxies discovered, 10 validated, all 9 UI sections.

### Android
- Same source-seeding and TLS fixes; `ProxyService` now calls `Python.start(AndroidPlatform(...))` before importing the bridge and reports bridge errors to `backend_error.txt` in filesDir.
- `/health` distinguishes fatal backend failure from gateway-start warnings; `READY` is reported as long as the controller loaded.
- Added `sources_enabled`, `logs` to `/api/stats` and `source_diagnostics`/`source_test` actions.

### Tests
- 33/33 backend tests PASS (added `33_packaged_sources_seeding`).
- Windows clean-runner EXE selftest: PASS (run 46054363004).
- Android emulator instrumentation: in progress at time of writing.

## v3.1.1 — Android cleartext + Windows runtime fixes (2026-11-27)

### Android
- Added `res/xml/network_security_config.xml`: cleartext permitted only for `localhost` / `127.0.0.1`, blocked externally; referenced from AndroidManifest.
- Bridge URL switched to `http://localhost:8765` so Android NSC domain matching applies.
- Lazy backend imports, `/health` readiness, retry/wait logic, port-conflict reuse, automatic gateway startup.
- Home dashboard hides the localhost endpoint; Downloads navigation label shortened to "Files"; buttons use weighted rows.
- Worker-selection dialog and async discovery preserved.

### Windows
- Fixed `TclError: bad option "-width"` by moving `width` from `.pack()` to the `ttk.Label` widget (2 sites); audited every `.pack()/.grid()/.place()` call.
- Replaced onedir build with standalone **onefile** PyInstaller (`--onefile --windowed --clean`) via `desktop/build_windows.py`; python311.dll, Tcl/Tk and all dependencies embedded.
- Rebuilt Inno Setup installer to reference the single onefile EXE.
- CI selftest now builds all nine UI sections and verifies backend/gateway/internet.

### Tests
- Windows clean-runner EXE selftest: PASS.
- Android emulator instrumentation: see TEST_REPORT.md for the current actual result (not assumed).

## v3.1.0 — Critical bug fixes (2026-11-27)

### Fixed
- **Android Find Proxies crash:** missing `rich` dependency in Chaquopy caused the Python bridge import chain to fail; added `rich`, made bridge imports lazy, added error-reporting `/health`, and wrapped all Kotlin bridge calls in exception handling.
- **Worker selection:** Find Proxies now opens a dialog with 10/50/100/200/500 + Custom (default 50, safe device cap 200 on Android), starts discovery asynchronously and polls real progress/counts.
- **Automatic backend/gateway startup:** gateway auto-starts on Android and Windows launch; independent Internet, Backend and Gateway statuses are shown.
- **Layout:** weighted buttons and compact rows prevent overlapping controls on phones and laptops.
- Backend config migrated to v4 with `gateway.auto_start`.

### Verified
- Crash reproduced locally and fix verified with `rich` deliberately blocked (server stays up, reports error).
- 32/32 backend tests PASS; APK/EXE rebuilt via GitHub Actions and verified genuine.
- Physical-device and interactive-GUI tests marked NOT TESTED.

## v3.0.0 — Desktop & Mobile Edition (2026-11-27)

### Added
- `backend/controller.py` — UI-agnostic backend controller and background worker shared by all frontends.
- `shared/exports.py` — unified TXT/CSV/JSON export engine with history, custom folders and address formats.
- `android/` — Kotlin + Jetpack Compose application (Home, Proxies, Gateway, Downloads, Settings), foreground service with notification and stop action, Chaquopy bridge to the Python backend, adaptive shield/nodes launcher icon, minimal permission set.
- `desktop/` — lightweight Tkinter desktop app with nine sidebar sections, sortable multi-select proxy table, right-click copy, keyboard shortcuts, system tray, gateway controls, export dialogs and PyInstaller/Inno Setup packaging files.
- `.github/workflows/build-android.yml` and `build-windows.yml` — reproducible APK/EXE/Setup builds.
- `tests/fixtures/localhost.crt` + key — self-signed test certificate enabling a real TLS listener test.
- `assets/generate_icons.py` — original shield/nodes icon generator.

### Fixed (v2 audit)
- **Stress-test criteria:** now require a measured success rate (≥95% PASS, ≥80% PARTIAL). Root cause of 265/500: the per-user connection limit was applied to anonymous clients; fixed — 500/500 now succeed in controlled local tests.
- **TLS listener:** verified with a real TLS-wrapped request (previously BLOCKED).
- **Destination security:** hostname destinations are DNS-resolved with a bounded timeout and private results rejected; loopback destinations now default-deny and are opt-in only.
- **Port documentation:** localhost `127.0.0.1:8080` documented consistently in gateway, README, CLI and both UIs.
- **Long-duration stability and high-concurrency reliability:** re-tested with reliable local fixtures (results in `TEST_REPORT.md`).

### Preserved
- All v2 discovery sources, discovery/validation engines, six rotation modes, country filters, exports, CLI menu, security modules and 232 existing database records.

### Versioning
- Version 3.0.0; `config_version=3` with v1/v2 config migration.

## v2.0.0 — Production Edition (2026-11-27)

### Upgraded
- ** gateway** (existing module improved, not replaced): per-connection rotation preserved; added circuit breakers with exponential backoff, quarantine/recovery, global and per-user connection caps, per-client rate limiting, destination policies, session tokens, optional TLS, auth-failure logging, freshness checks and explicit fail-closed errors.
- **Config**: `config_version=2`, sane 15-minute pool refresh / 5-minute health defaults, migration from v1's 1440-minute intervals, new security/health sections, PBKDF2 credential fields.
- **Storage**: in-place SQLite migration to schema v2 adding `health_state`, `consecutive_failures`, `last_success`, `quarantine_until`, `unique_exit_ip`; health events table; quarantine/recovery/prune/expiry APIs; capacity reporting; duplicate detection; atomic writes retained.
- **Discovery**: rotating per-source log files (size-based rotation) instead of unbounded appends.
- **CLI**: preserved Rich design; added v2 dashboard (online status, endpoint, country, mode, eligible proxies, unique exit IPs, health distribution, CPU/RAM, last refresh/health, uptime, version, capacity warnings); multi-country selection; health/refresh-now actions; security settings.
- **Checker**: `remove_dead` flag so gateway health cycles can quarantine and recover instead of deleting rows.

### Added
- `proxyhunter/security.py` — PBKDF2 password hashing, constant-time verification, sessions, IP allowlists, destination policies, token buckets, connection accounting.
- `proxyhunter/logging_utils.py` — size-rotating loggers.
- `tests/test_suite.py` — 30 mandatory controlled tests plus TLS status check.
- `TEST_REPORT.md`, `PRODUCTION_READINESS.md`.

### Fixed
- Hostname destinations wrongly rejected by `deny_private`.
- Dead proxy records lost (no path to recovery).
- Excessive legacy health intervals.
- Plaintext credential storage compatibility.
- Stale metrics after gateway start.
- Retry loop could retry the same failed upstream (now excluded).

### Compatibility
- All v1 CLI options and worker presets preserved.
- Existing SQLite data preserved through migration (45/45 rows verified).
- v1 configuration upgraded in memory without discarding user values.
- Full backup kept at `ProxyHunter_v1.0_backup`.

## v1.0.0 (2026-11-26)
- Initial discovery, validation, export, country management, rotating gateway and Rich CLI.
