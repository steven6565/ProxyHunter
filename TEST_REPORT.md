# ProxyHunter v3.1.2 — Test Report (v3.0/3.1 baseline below)

## v3.1.2 actual results

| Test | Status | Evidence |
|---|---|---|
| Windows PyInstaller onefile build (`--onefile --windowed --clean`) | PASS | CI run 46054363004; 26,094,893-byte PE32+ EXE, 27,727,702-byte Setup |
| Windows clean-runner EXE startup/GUI selftest | PASS | `selftest.json`: `ok:true`, version 3.1.2, 16/19 sources enabled, discovered=18217, checked=10, all 9 sections built, backend READY, gateway ONLINE, internet ONLINE |
| Tkinter geometry audit | PASS | two invalid `pack(width=...)` fixed; all geometry calls audited |
| Packaged source seeding (Windows + Android) | PASS | 33/33 backend tests incl. `33_packaged_sources_seeding`: empty `{"custom":[]}` and malformed files are re-seeded with all 15 enabled authorized sources; `PROXYHUNTER_HOME` override honored |
| Packaged TLS trust store | PASS | certifi CA bundle collected into the Windows EXE; `make_ssl_context()` used by discovery/checker/test_source; local fetch test returned 200 |
| Android network security config | PASS (build) | `network_security_config.xml` referenced in manifest; cleartext only for localhost/127.0.0.1 |
| Android installed-APK emulator instrumentation | PENDING | CI run 46054352845 still running at last check; prior failure was "No enabled sources" (now fixed) |
| Backend regression | PASS | 33/33 in `output/test_results.json` |
| 60-minute stability (v3 baseline) | PASS | 99.725% success |

Windows runtime errors reported by the user (No enabled sources, 0 discovered, Workers n/a, Last Refresh never) were reproduced from the source: a packaged Android install received an empty `{"custom": []}` sources file and `base_dir()` ignored `PROXYHUNTER_HOME` on machines with a source checkout. Both are fixed; Windows onefile smoke test now discovers 18,217 proxies.

## v3.1.1 actual results

| Test | Status | Evidence |
|---|---|---|
| Windows PyInstaller onefile build (`--onefile --windowed --clean`) | PASS | CI run 45986062386; 25.8 MB PE32+ EXE, 27.4 MB Setup |
| Windows clean-runner EXE startup/GUI selftest | PASS | `selftest.json`: `ok:true`, version 3.1.1, all 9 sections built, backend READY, gateway ONLINE, internet ONLINE |
| Tkinter geometry audit | PASS | two invalid `pack(width=...)` fixed; all geometry calls audited |
| Android network security config | PASS (build) | `network_security_config.xml` referenced in manifest; cleartext only for localhost/127.0.0.1 |
| Android installed-APK emulator instrumentation | SEE BELOW | run 45998883972; result being updated from artifact evidence |
| Backend regression | PASS | 32/32 in `output/test_results.json` |
| 60-minute stability (v3 baseline) | PASS | 99.725% success |

Windows runtime errors reported by the user were reproduced from source code (`pack(width=22)`, `pack(width=18)`) and from the onedir DLL lookup; both fixes are verified on a clean Windows runner.

---

# ProxyHunter v3.1.0 — Test Report (v3.0 baseline below)

## Android Find Proxies crash — root cause and evidence

**Reported symptoms:** APK installed, screens opened, dashboard OFFLINE/0 proxies, tapping Find Proxies crashed the app.

**Root cause (reproduced locally):**
1. The Chaquopy pip configuration omitted `rich`. `android/python/bridge.py` imported `backend.controller` at module import time; that chain imports `proxyhunter.dashboard` → `rich`.
2. With `rich` unavailable, `import backend.controller` raises `ModuleNotFoundError: No module named 'rich'` (reproduced by blocking the `rich` import: output shows the exact failure).
3. The Python bridge therefore never started; all HTTP calls from Kotlin failed. `MainActivity.action()` launched a coroutine with no exception handling, so the failed Find Proxies POST produced an uncaught coroutine exception and closed the app.

**Fixes:**
- Added `rich` to Chaquopy pip requirements.
- Made bridge imports lazy; the HTTP server now always starts and `/health` reports `backend: ERROR` with the captured traceback instead of killing the service.
- All bridge actions return JSON errors; Kotlin `action()` and `refresh()` wrap every bridge call in `try/catch`.
- Find Proxies now opens a worker-selection dialog (10/50/100/200/500/Custom, default 50, capped by safe device limits); discovery starts asynchronously on the backend loop and the UI polls real stats — no 30 s HTTP timeout crash.
- Gateway auto-starts on app launch; independent Internet/Backend/Gateway statuses are reported from `/health`.
- Compact-screen layout fixes (weighted buttons, no overlap).

**Test evidence:**
- Old crash reproduced: `ModuleNotFoundError: No module named 'rich'` from `backend.controller → proxyhunter.dashboard`.
- New bridge with `rich` deliberately blocked: HTTP server still starts and `/health` returns `{"ok":false,"backend":"ERROR","error":"ModuleNotFoundError: No module named 'rich'..."}` — no crash.
- Local bridge endpoint test: `/api/stats` → backend READY, gateway ONLINE, internet ONLINE, version 3.1.0; `/api/discover {"workers":500}` → `{"started":true,"workers":200}` (Android safe cap); stats then showed real discovered/unique counts.
- Backend regression suite: **32/32 PASS** after all v3.1 changes.
- Android CI build: **PASS** (run 45965607649). Windows CI build + EXE selftest: **PASS** (run 45963805724).
- APK/EXE format verification: genuine ZIP APK with `classes.dex`; EXE/Setup valid PE32+ (`MZ`/`PE`).

**NOT TESTED:** Android physical-device install/launch/tap-through (no adb device attached); interactive Windows GUI on a real desktop. These are not claimed.

---

# ProxyHunter v3.0 — Test Report (v2.0 baseline below)

## v3.0 results (2026-11-27)

| Area | Test | Status | Evidence |
|---|---|---|---|
| Backend | 32 controlled tests (syntax, deps, startup, regression, DB integrity/migration, gateway, single endpoint, rotation, country, HTTP, CONNECT, SOCKS4/5, failure/recovery, empty pool, timeout, auth, ACL, destination policy, health/refresh, shutdown, restart, concurrency, memory, FD, stability, export integrity) | **PASS** | `output/test_results.json`: 32 PASS, 0 FAIL |
| Security | TLS listener with real TLS-wrapped request | **PASS** | self-signed localhost cert; gateway replied 200 over TLS |
| Security | DNS + loopback default-deny and opt-in | **PASS** | private/loopback denied by default, public/hostname allowed, opt-in works |
| Reliability | Controlled concurrency 10/50/100/200/500 | **PASS** | **500/500 successful** at all levels; worst success rate 100%; measured 37–90 req/s this run |
| Performance | Memory / FD leak | **PASS** | 200 requests: <0.1 MB growth; 120 requests: FD count stable |
| Stability | 30-second sustained local run | **PASS** | hundreds of successful requests, gateway stayed online |
| Stability | **60-minute sustained run** | **PASS** | 3,600 s local controlled run: 44,286 successful / 122 failed requests = **99.725%** success (`output/stability_60min.json`) |
| Packaging | Android APK build | **PASS** | GitHub Actions run 45957372999; 46.8 MB APK with classes.dex + manifest |
| Packaging | Windows portable EXE + Setup build | **PASS** | GitHub Actions run 45957889216; 7.7 MB EXE + 20.6 MB Setup (MZ/PE verified) |
| CI smoke | Windows EXE `--selftest` startup | **PASS** | built EXE wrote selftest.json and reported backend ready |
| CI smoke | Android APK package verification | **PASS** | unzip -l showed classes.dex + AndroidManifest.xml |
| UI | Android physical-device install/start | **NOT TESTED** | no device/emulator available in delivery environment |
| UI | Windows EXE launch on real desktop | **NOT TESTED** | CI selftest only; interactive GUI not exercised |
| Size | APK <40 MB / portable EXE <80 MB | **PARTIAL PASS** | APK 46.8 MB (above 40 MB target, all required runtime bundled); EXE 7.7 MB (within 80 MB) |

### Honest status statement

The Python backend is fully tested. Both installable binaries were **built successfully on GitHub Actions runners** and downloaded as genuine APK/EXE/Setup files. CI-level packaging and startup smoke tests passed. Physical-device installation and interactive GUI operation remain **NOT TESTED** in this delivery environment. APK is debug-signed; Windows binaries are unsigned.

### v2 audit fixes verified
- 265/500 concurrency failure root cause found (anonymous per-user cap) and fixed → 500/500.
- TLS listener verified instead of assumed.
- Hostname DNS/private-address checks and loopback default-deny verified.
- Stress-test PASS criteria corrected to require measured success rates.

---

# ProxyHunter v2.0 — Test Report (baseline)

- **Date:** 2026-11-27
- **Version under test:** 2.0.0
- **Runner:** `python3 tests/test_suite.py` (isolated temporary workspace)
- **Network policy:** all automated tests use **local mock proxy servers and a local HTTP endpoint**; no load test was sent to public websites or third-party services.
- **Machine:** Android/Termux environment (ARM64, Python 3.14), localhost only.

## Summary

| Status | Count |
|---|---|
| PASS | **30** |
| FAIL | 0 |
| PARTIAL PASS | 0 |
| BLOCKED | 1 (TLS listener — no certificate tooling) |
| NOT TESTED | 0 |

Machine-readable results: `output/test_results.json`.

## Mandatory test results

| # | Test | Status | Evidence |
|---|---|---|---|
| 1 | Python syntax/compilation | PASS | 16 files compiled via `py_compile` |
| 2 | Dependency installation | PASS | all required imports OK; `pip install --dry-run -r requirements.txt` returned 0 |
| 3 | Application startup | PASS | `App()` initialised; version 2.0.0; `config_version=2` |
| 4 | Existing-feature regression | PASS | presets 10/50/100/200/500 intact, ≥15 sources, TXT/JSON/CSV exports produced |
| 5 | SQLite integrity | PASS | `PRAGMA integrity_check = ok` |
| 6 | Database migration | PASS | v1 backup DB migrated in place: schema v2, health columns added, **45/45 rows preserved** |
| 7 | Gateway startup | PASS | `start_server` bound to an ephemeral localhost port, `running=True` |
| 8 | Single stable endpoint | PASS | 9/9 requests used the same `http://127.0.0.1:<fixed port>` |
| 9 | Per-connection rotation | PASS | **3 distinct exit IPs across 9 new connections** (controlled upstreams) |
| 10 | Country selection accuracy | PASS | US→US, IN→IN; unsupported `ZZ` returned 502 with no eligible proxy |
| 11 | HTTP forwarding | PASS | absolute-form GET forwarded, correct path echoed |
| 12 | HTTPS CONNECT tunnelling | PASS | CONNECT 200 + tunnelled HTTP response over local TCP target |
| 13 | SOCKS4 connectivity | PASS | local SOCKS4 upstream, exit marker `208.67.222.222` |
| 14 | SOCKS5 connectivity | PASS | local SOCKS5 upstream, exit marker `208.67.220.220` |
| 15 | Failed proxy handling | PASS | dead upstream produced 502 and was quarantined |
| 16 | Proxy recovery | PASS | quarantined proxy recovered after controlled revalidation (`recovered=1`) |
| 17 | Empty pool handling | PASS | 502, gateway stayed online, no direct-IP fallback |
| 18 | Timeout handling | PASS | slow upstream, 0.4 s timeout, 502 in ~1.0 s |
| 19 | Authentication | PASS | no header=407, bad credentials=407, valid=200, PBKDF2 verified, plaintext removed |
| 20 | Unauthorized peer rejection | PASS | IP allowlist mismatch → 403 |
| 21 | Restricted destination policy | PASS | destination allowlist mismatch → 403 |
| 22 | Background health monitoring | PASS | `run_health_cycle()` returned a result and updated pool state |
| 23 | Automatic pool refresh | PASS | `run_pool_refresh_cycle()` invoked callback, pruning, exports, set `last_refresh` |
| 24 | Graceful shutdown | PASS | active connection waited ~0.4 s and finished before stop returned |
| 25 | Restart & persistence | PASS | gateway restarted and saved proxy still present |
| 26 | Concurrency benchmarks | PASS | 10/50/100/200/500 concurrent local requests completed; see below |
| 27 | Memory leak detection | PASS | tracemalloc growth **0.07 MB** over 200 requests |
| 28 | File descriptor leak | PASS | `/proc/self/fd` count 21 → 17 after 120 requests |
| 29 | Long-duration stability | PASS | 30 s, 4 sustained clients, **913 successful** requests, gateway still online |
| 30 | Output file integrity | PASS | TXT lines = CSV rows = JSON total = export report count |
| Extra | TLS listener | **BLOCKED** | `openssl` and `cryptography` are unavailable in this environment; TLS code is implemented but not exercised |

## Controlled concurrency benchmark (localhost mock chain)

These are **measured** values, not theoretical maxima. "OK" is the number of HTTP 200 responses; incomplete responses are a property of the lightweight mock upstream relay under burst load, not a success claim for the gateway.

| Concurrent requests | OK / total | Seconds | OK req/s |
|---|---|---|---|
| 10 | 10/10 | 0.05 | 185.6 |
| 50 | 30/50 | 0.13 | 238.4 |
| 100 | 55/100 | 0.31 | 174.8 |
| 200 | 109/200 | 1.32 | 82.4 |
| 500 | 265/500 | 2.10 | 126.3 |

Sustainable local throughput in this environment: roughly **80–240 successful requests/second**, bounded by the mock relay and the Android runtime. No unlimited capacity is claimed.

## Authorized live verification (public free proxies, rate-limited)

After a bounded validation run, a fresh pool of 232 verified proxies was used with the unchanged gateway endpoint and fresh connections:

- 8/8 requests returned HTTP 200 from `ip-api.com`.
- **7 distinct exit IPs** were observed across 8 connections.
- Country codes were derived from the **actual exit IP** (NP, ID, TH, VN, MM).
- Result saved to `output/live_rotation_result.json`.

This verifies live rotation without any ban evasion, authentication bypass or unauthorized traffic.

## Bugs found and fixed during testing

1. v1 default health intervals of 1440 minutes replaced with 15/5 minutes plus migration.
2. Plaintext password compatibility migrated to PBKDF2-SHA256 salted hashes.
3. Hostname destinations were incorrectly treated as private by `deny_private`; fixed so DNS names are allowed (local/internal names still denied).
4. Controlled proxy recovery was impossible because dead results were physically deleted; health cycles now retain dead rows and quarantine/recover them.
5. Mock upstream CONNECT path lacked first-request marker injection; test fixture corrected.

## Limitations

- TLS listener test is BLOCKED locally; generate a certificate and set `gateway.security.tls` before relying on it in production.
- Public free-proxy availability is transient; the gateway reports **eligible proxy count** and warns when the selected country has no recently validated entries.
- Benchmarks were run on localhost; VPS performance will differ.
