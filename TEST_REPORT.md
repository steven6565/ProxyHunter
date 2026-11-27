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
| Stability | **60-minute sustained run** | **NOT TESTED** | session time insufficient; automated local fixture exists, run on VPS/CI |
| Packaging | Android APK build/install | **BLOCKED** | no Android SDK/Gradle in delivery environment; CI workflow provided |
| Packaging | Windows EXE / Setup build/install | **BLOCKED** | no Windows toolchain, PyInstaller or tkinter here; CI workflow provided |
| UI | Android Compose UI runtime | **NOT TESTED** | build blocked; sources complete |
| UI | Windows Tkinter UI runtime | **NOT TESTED** | tkinter unavailable here; sources complete |
| Size | APK <40 MB / portable EXE <80 MB | **BLOCKED** | cannot measure without built binaries |

### Honest status statement

The Python backend is fully tested. The two graphical frontends and their installable binaries are **implemented but not built or installed in this environment**. They are not claimed as supported/tested platforms until the CI workflows produce and install the artifacts. No fake APK/EXE files were created.

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
