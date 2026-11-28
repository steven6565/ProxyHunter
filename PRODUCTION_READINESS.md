# ProxyHunter v3.2.0 — Production Readiness Assessment (v3.0 baseline below)

## v3.1.2 verdict

**Packaged discovery root cause FIXED and verified on a clean Windows runner.**
**Android source-seeding fix applied; emulator evidence pending.**

- Root cause reproduced and fixed: packaged installs seeded an empty `{"custom": []}` sources file and `base_dir()` ignored `PROXYHUNTER_HOME`; discovery now re-seeds all 19 authorized sources.
- TLS trust store fixed via `proxyhunter/net.py` + certifi on Windows (collected into EXE) and Android (pip-installed).
- Windows clean-runner selftest: PASS — 16/19 sources enabled, 18,217 discovered, 10 validated, all 9 sections, backend READY, gateway/internet ONLINE.
- Backend regression: 33/33 PASS; 60-minute stability 99.725%.
- Android physical-device tap-through and interactive Windows GUI remain NOT TESTED.

## v3.1 verdict

**Critical Android Find Proxies crash: FIXED and verified at code-path/CI level.**
**Packaged apps: BUILT. Device-level confirmation: PENDING.**

- Root cause reproduced locally (missing `rich` in Chaquopy pip → bridge import failure → uncaught Kotlin coroutine exception).
- Fixed: lazy imports, error-reporting `/health`, exception-safe Kotlin calls, added `rich`, async worker-selection discovery, auto-start gateway, independent statuses, compact layouts.
- Backend regression: 32/32 PASS; 60-minute stability previously PASS (99.725%).
- Android APK and Windows EXE/Setup rebuilt successfully and verified as genuine files.
- Android physical-device tap-through and interactive Windows GUI remain **NOT TESTED** — no device/emulator or Windows desktop in the delivery environment.

---

# ProxyHunter v3.0 — Production Readiness Assessment (v2.0 baseline below)

## v3.0 verdict

**BACKEND: PASS. PACKAGED APK/EXE: BUILT AND VERIFIED; DEVICE-LEVEL TESTS PENDING.**

| Deliverable | Status |
|---|---|
| Python backend v3.0 (32 tests) | PASS |
| CLI advanced mode | PASS (preserved and version-updated) |
| Android Compose APK | **BUILT via CI** (run 45957372999); genuine APK verified |
| Windows EXE + Setup | **BUILT via CI** (run 45957889216); genuine PE binaries verified |
| Windows EXE selftest on CI | PASS |
| Installed/started Android app on physical device | NOT TESTED |
| Interactive Windows GUI on real desktop | NOT TESTED |
| 60-minute stability run | **PASS** — 3,600 s, 44,286 success / 122 failure = 99.725% |
| Code signing | Android debug-signed; Windows unsigned |

### Security posture (v3)
- Localhost gateway default; remote bind refused without PBKDF2 credentials + explicit flag.
- Loopback destinations now **default-deny**; hostnames are DNS-resolved and private results rejected.
- TLS listener verified with a real certificate.
- Rotation never falls back to the direct IP; empty pool ⇒ clear 502.
- Free public proxies remain untrusted: documentation warns against passwords, payments and confidential data.

### Platform support statement
Do not treat Android or Windows as "supported/tested" until the GitHub Actions artifacts have been downloaded, installed and smoke-tested on real devices. The source implementations are complete and the reproducible workflows are provided.

---

# ProxyHunter v2.0 — Production Readiness Assessment (baseline)

**Verdict: CONDITIONAL PASS for authorized deployments.**

Implementation is complete. All 30 mandatory functional tests passed in a controlled local environment; one optional TLS test is BLOCKED because no certificate tooling is installed. The application is suitable for authorized network testing on localhost or on a hardened VPS after the deployment checklist below is completed.

## Client requirement coverage

| Requirement | Status | Notes |
|---|---|---|
| One stable proxy endpoint | PASS | `http://127.0.0.1:8080` by default; unchanged across all connections |
| Automatic rotation on new connection | PASS | 3 distinct controlled exits; 7 distinct live exits in 8 connections |
| Country-specific selection | PASS | Single or multiple ISO codes; verified against exit-IP geo; fail-closed on empty selection |
| Continuously maintained pool | PASS | 15-min refresh, 5-min health, quarantine/recovery, expiry |
| No direct-IP fallback | PASS | Connection is refused with 502 before any destination socket is opened |
| Multiple simultaneous connections | PASS | 500 concurrent local requests completed; global + per-user caps |
| Preserve v1 features/data | PASS | presets, sources, exports, DB migration 45/45 rows |
| Secure remote access | PARTIAL | Auth, hashing, IP allowlist, destination policy, per-user caps implemented; TLS code present but **TLS test BLOCKED** |
| Accurate capacity reporting | PASS | dashboard shows eligible proxies, unique exit IPs, warnings |

## Security assessment

- **Default posture:** localhost bind, no authentication required, deny-private destination policy. Safe default for desktop/Termux use.
- **Credentials:** PBKDF2-HMAC-SHA256, 160,000 iterations, random 16-byte salt, constant-time comparison; plaintext is migrated out of config on first load.
- **Remote access:** refused unless `auth.enabled`, username+hash and `allow_remote_access: true` are all set. TLS certificate/key paths validated at startup.
- **Access control:** CIDR/IP allowlist, destination allowlist/policy, per-client token bucket, global connection semaphore, per-user connection cap, session TTL with Bearer tokens.
- **Logging:** authentication failures and denied destinations go to a size-rotated `output/logs/gateway_auth.log`; per-source discovery logs are rotated too.
- **Abuse prevention:** rotation is per connection only; there is no ban-evasion or CAPTCHA-bypass feature; users must respect destination rate limits and access controls.

## Resource limits (measured, local)

| Metric | Result |
|---|---|
| Memory growth (200 requests) | 0.07 MB |
| File descriptors (120 requests) | 21 → 17 |
| 30-second stability | 913 successful requests, gateway online |
| Sustainable throughput | ~80–240 successful req/s (local mock chain) |

## VPS deployment checklist (authorized use only)

1. `bash install.sh` (Ubuntu/Debian/VPS) or `install.bat` (Windows).
2. Generate a certificate (`openssl req -x509 -newkey rsa:2048 ...`) and set `gateway.security.tls.enabled=true` with cert/key paths.
3. Set `gateway.bind` to the VPS interface, create credentials via menu **G → 6**, and set `allow_remote_access=true`.
4. Configure `security.ip_allowlist` with your management network and `destination_policy`/`destination_allowlist` for authorized targets only.
5. Set `max_connections`, `max_connections_per_user`, `rate_limit_per_second` to conservative values.
6. Use a firewall to restrict the gateway port to approved source IPs.
7. Monitor `output/logs/gateway_auth.log` and `output/test_results.json`.

## Remaining limitations

- TLS listener implemented but not exercised here (no openssl/cryptography). Marked **BLOCKED**, not PASS.
- Public free proxies are inherently unreliable; capacity is reported honestly and never advertised as unlimited.
- Rate limits for public validation endpoints remain enabled by default (15/s); do not disable them to inflate benchmark numbers.
- No GUI; management is via the preserved Rich CLI.
- Android/Termux cannot build `psutil`; CPU usage shows `n/a` and RAM uses `/proc` (expected platform limitation).

## Final verdict

- **Functional correctness:** PASS (30/30 mandatory tests).
- **Security controls:** PARTIAL PASS until TLS is validated in the target VPS environment.
- **Data integrity:** PASS.
- **Resource usage:** PASS within documented limits.
- **Overall:** **CONDITIONAL PASS** — production use is approved for authorized testing with the VPS checklist completed; TLS validation must be performed before exposing the gateway beyond localhost.
