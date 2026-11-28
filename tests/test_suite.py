#!/usr/bin/env python3
"""ProxyHunter v2.0 controlled test suite.

All network tests use local mock proxy servers and local HTTP endpoints. No
load test is performed against public websites or third-party services.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import json
import os
import py_compile
import shutil
import socket
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="proxyhunter-v2-tests-"))

for name in ("proxyhunter", "main.py", "bootstrap.py", "config.json", "sources.json", "requirements.txt", "tests"):
    src = SRC / name
    if src.is_dir():
        shutil.copytree(src, WORK / name, ignore=shutil.ignore_patterns("__pycache__"))
    elif src.exists():
        shutil.copy2(src, WORK / name)
(WORK / "output" / "logs").mkdir(parents=True, exist_ok=True)
os.chdir(WORK)
sys.path.insert(0, str(WORK))

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402

from main import App  # noqa: E402
from proxyhunter import __version__  # noqa: E402
from proxyhunter.config import WORKER_PRESETS, base_dir, load_config  # noqa: E402
from proxyhunter.discovery import load_sources  # noqa: E402
from proxyhunter.models import Proxy, utc_now  # noqa: E402
from proxyhunter.security import hash_password, verify_password  # noqa: E402

RESULTS: list[dict] = []
DETAILS: dict[str, str] = {}


def record(name: str, status: str, detail: str = "") -> None:
    detail = str(detail)
    RESULTS.append({"name": name, "status": status, "detail": detail})
    DETAILS[name] = detail
    mark = {"PASS": "PASS", "FAIL": "FAIL", "PARTIAL PASS": "PARTIAL", "BLOCKED": "BLOCKED", "NOT TESTED": "N/A"}[status]
    print(f"[{mark:8}] {name}: {detail[:160]}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------- fixtures
async def start_target():
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({
            "status": "success",
            "query": request.headers.get("X-Exit-IP", "127.0.0.1"),
            "countryCode": request.headers.get("X-Exit-Country", "US"),
            "city": "TestCity", "isp": "TestISP", "path": request.path,
        })

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, port


async def relay(reader, writer) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (OSError, asyncio.CancelledError, ConnectionResetError):
        pass


class MarkerHTTPProxy:
    """Local authorized HTTP proxy injecting exit-IP/country marker headers."""

    def __init__(self, exit_ip: str, country: str = "US", slow: float = 0.0) -> None:
        self.exit_ip = exit_ip
        self.country = country
        self.slow = slow
        self.server = None
        self.port = 0
        self.connections = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _handle(self, reader, writer) -> None:
        self.connections += 1
        try:
            if self.slow:
                await asyncio.sleep(self.slow)
            head = await reader.readuntil(b"\r\n\r\n")
            first = head.split(b"\r\n", 1)[0].decode("utf-8", "replace")
            parts = first.split()
            method, target = parts[0], parts[1]
            from urllib.parse import urlparse
            if method == "CONNECT":
                host, port_text = target.rsplit(":", 1)
                host = host.strip("[]")
                port = int(port_text)
            else:
                parsed = urlparse(target)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 80
            up_reader, up_writer = await asyncio.open_connection(host, port)
            marker = (
                f"X-Exit-IP: {self.exit_ip}\r\nX-Exit-Country: {self.country}\r\n"
            ).encode()
            if method == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                # The gateway sends the real request through the tunnel; mark
                # its first request so the local target can report the exit.
                tunnel_head = await reader.readuntil(b"\r\n\r\n")
                first = tunnel_head.split(b"\r\n", 1)[0]
                up_writer.write(first + b"\r\n" + marker + tunnel_head[len(first) + 2:])
                await up_writer.drain()
            else:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                remainder = head[head.index(b"\r\n") + 2:]
                up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode() + marker + remainder)
                await up_writer.drain()
            await asyncio.gather(relay(reader, up_writer), relay(up_reader, writer))
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()


class MarkerSocksProxy:
    """Minimal local SOCKS4/SOCKS5 server with marker injection."""

    def __init__(self, version: int, exit_ip: str, country: str) -> None:
        self.version = version
        self.exit_ip = exit_ip
        self.country = country
        self.server = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    @property
    def url(self) -> str:
        return f"socks{self.version}://127.0.0.1:{self.port}"

    async def _handle(self, reader, writer) -> None:
        try:
            if self.version == 5:
                greeting = await reader.readexactly(2)
                await reader.readexactly(greeting[1])
                writer.write(b"\x05\x00")
            else:
                data = await reader.readexactly(8)
                while await reader.readexactly(1) != b"\x00":
                    pass
                port = int.from_bytes(data[2:4], "big")
                host = socket.inet_ntoa(data[4:8])
                writer.write(b"\x00\x5a" + data[2:8])
                await writer.drain()
                await self._tunnel(reader, writer, host, port)
                return
            request = await reader.readexactly(4)
            atyp = request[3]
            if atyp == 1:
                host = socket.inet_ntoa(await reader.readexactly(4))
            elif atyp == 3:
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode()
            else:
                host = socket.inet_ntoa(await reader.readexactly(4))
            port = int.from_bytes(await reader.readexactly(2), "big")
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            await self._tunnel(reader, writer, host, port)
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    async def _tunnel(self, reader, writer, host, port) -> None:
        up_reader, up_writer = await asyncio.open_connection(host, port)
        head = await reader.readuntil(b"\r\n\r\n")
        first = head.split(b"\r\n", 1)[0]
        marker = f"X-Exit-IP: {self.exit_ip}\r\nX-Exit-Country: {self.country}\r\n".encode()
        up_writer.write(first + b"\r\n" + marker + head[len(first) + 2:])
        await up_writer.drain()
        await asyncio.gather(relay(reader, up_writer), relay(up_reader, writer))


def add_proxy(storage, host: str, port: int, protocol: str = "http", country: str = "US",
              exit_ip: str | None = None, latency: float = 5.0) -> str:
    key = f"{protocol}://{host}:{port}"
    exit_ip = exit_ip or host
    storage.conn.execute(
        """INSERT OR REPLACE INTO proxies
           (key, host, port, protocol, working, response_time_ms, country, country_code,
            city, isp, exit_ip, source, last_checked, error, health_state,
            consecutive_failures, last_success, quarantine_until, unique_exit_ip)
           VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,'','healthy',0,?,'',?)""",
        (key, host, port, protocol, latency, country, country, "TestCity", "TestISP",
         exit_ip, "controlled-test", utc_now(), utc_now(), exit_ip),
    )
    storage.conn.commit()
    return key


async def request_via_gateway(port: int, url: str, auth: str | None = None, timeout: int = 12):
    headers = {"Connection": "close"}
    if auth:
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                url, proxy=f"http://127.0.0.1:{port}", headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                body = await response.text()
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    parsed = {"error": body[:160]}
                return response.status, parsed
        except aiohttp.ClientHttpProxyError as exc:
            return int(getattr(exc, "status", 0) or 502), {"error": str(exc)[:120]}
        except Exception as exc:  # noqa: BLE001
            return None, {"error": f"{type(exc).__name__}: {exc}"}


def fresh_gateway(app, port: int):
    gw = app.gateway
    gw.cfg["port"] = port
    gw.cfg["bind"] = "127.0.0.1"
    gw.cfg["security"]["destination_policy"] = "all"
    gw.cfg["security"]["max_connections"] = 600
    gw.global_sem = asyncio.Semaphore(600)
    gw.countries = {"all"}
    gw.circuits.clear()
    gw.failed_keys.clear()
    gw.reset_rotation()
    return gw


# -------------------------------------------------------------------- test cases
def test_syntax() -> None:
    files = sorted(SRC.glob("**/*.py"))
    failed = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed.append(f"{path.name}: {exc}")
    record("01_python_syntax_compilation", "PASS" if not failed else "FAIL",
           f"compiled {len(files)} files" if not failed else "; ".join(failed))


def test_dependencies() -> None:
    import subprocess
    modules = ["aiohttp", "aiohttp_socks", "python_socks", "bs4", "rich", "geoip2", "psutil"]
    optional = {"psutil"}
    missing = []
    for module in modules:
        try:
            __import__(module)
        except ImportError:
            if module not in optional:
                missing.append(module)
    try:
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run", "-r", str(WORK / "requirements.txt")],
            capture_output=True, text=True, timeout=90,
        )
        install_ok = install.returncode == 0
    except Exception:  # noqa: BLE001
        install_ok = False
    ok = not missing and install_ok
    record("02_dependency_installation", "PASS" if ok else "PARTIAL PASS",
           f"imports missing={missing}, pip dry-run={'ok' if install_ok else 'failed'}")


def test_startup() -> None:
    app = App()
    ok = __version__ == "3.4.0" and app.config["config_version"] == 4
    record("03_application_startup", "PASS" if ok else "FAIL",
           f"version={__version__}, config_version={app.config['config_version']}")
    app.close()


def test_regression() -> None:
    config = load_config()
    ok_presets = WORKER_PRESETS == {"low": 10, "normal": 50, "fast": 100, "high": 200, "advanced": 500}
    ok_sources = len([x for cat, v in json.loads((WORK / "sources.json").read_text()).items()
                      if not cat.startswith("_") and isinstance(v, list) for x in v]) >= 15
    storage = __import__("proxyhunter.storage", fromlist=["Storage"]).Storage(config)
    ok_db = storage.count_working() >= 0
    storage.export_all()
    ok_exports = all((WORK / "output" / f).exists() for f in
                     ("working_proxies.txt", "working_proxies.json", "working_proxies.csv"))
    storage.close()
    ok = all((ok_presets, ok_sources, ok_db, ok_exports))
    record("04_existing_feature_regression", "PASS" if ok else "FAIL",
           f"presets={ok_presets}, sources={ok_sources}, exports={ok_exports}")


async def test_database_integrity() -> None:
    app = App()
    result = app.storage.conn.execute("PRAGMA integrity_check").fetchone()[0]
    app.close()
    record("05_sqlite_integrity", "PASS" if result == "ok" else "FAIL", f"integrity_check={result}")


def test_database_migration() -> None:
    backup_db = SRC.parent / "ProxyHunter_v1.0_backup" / "output" / "proxies.db"
    if not backup_db.exists():
        record("06_sqlite_migration", "BLOCKED", "v1.0 backup database not found")
        return
    target = WORK / "output" / "migration_test.db"
    shutil.copy2(backup_db, target)
    import sqlite3
    from proxyhunter.storage import Storage
    original = sqlite3.connect(target)
    before = original.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
    original.close()
    config = dict(load_config())
    storage = Storage(config)
    storage.conn.close()
    # Point a fresh Storage at the copied legacy DB by temporarily swapping.
    live = WORK / "output" / "proxies.db"
    shutil.copy2(live, WORK / "output" / "proxies_live_saved.db")
    shutil.copy2(target, live)
    migrated = Storage(config)
    version = migrated.schema_version
    columns = [row[1] for row in migrated.conn.execute("PRAGMA table_info(proxies)")]
    after = migrated.conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
    migrated.close()
    shutil.copy2(WORK / "output" / "proxies_live_saved.db", live)
    ok = version == 2 and after == before and "health_state" in columns and "quarantine_until" in columns
    record("06_sqlite_migration", "PASS" if ok else "FAIL",
           f"v{version}, rows {before}->{after}, health columns present={'health_state' in columns}")


async def gateway_tests() -> None:
    runner, target_port = await start_target()
    target_url = f"http://127.0.0.1:{target_port}/check"
    app = App()
    storage = app.storage
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    gw_port = free_port()
    gw = fresh_gateway(app, gw_port)

    # 07 gateway startup
    started = await gw.start()
    record("07_gateway_startup", "PASS" if started and gw.running else "FAIL",
           f"endpoint=http://127.0.0.1:{gw_port}, running={gw.running}")

    # 08 single endpoint + 09 rotation with three local upstreams
    marker_servers = [MarkerHTTPProxy("1.1.1.1", "US"), MarkerHTTPProxy("8.8.8.8", "IN"), MarkerHTTPProxy("9.9.9.9", "DE")]
    for server in marker_servers:
        await server.start()
        add_proxy(storage, "127.0.0.1", server.port, "http", server.country, server.exit_ip)
    gw.reload_pool()
    endpoint = f"http://127.0.0.1:{gw_port}"
    exits = []
    statuses = []
    for _ in range(9):
        status, data = await request_via_gateway(gw_port, target_url)
        statuses.append(status)
        exits.append(data.get("query"))
    single_ok = all(code == 200 for code in statuses) and len(set(exits)) >= 2
    record("08_single_stable_endpoint", "PASS" if all(code == 200 for code in statuses) else "FAIL",
           f"same endpoint used for {len(statuses)} requests; statuses={statuses}")
    record("09_per_connection_rotation", "PASS" if len(set(exits)) >= 2 else "FAIL",
           f"distinct exit IPs={len(set(exits))} of {len(exits)}: {exits}")

    # 10 country selection accuracy + insufficient country reporting
    ok_country, warning = gw.set_countries(["US"])
    us_ok = True
    for _ in range(3):
        status, data = await request_via_gateway(gw_port, target_url)
        us_ok &= status == 200 and data.get("countryCode") == "US"
    gw.set_countries(["IN"])
    in_ok = True
    for _ in range(2):
        status, data = await request_via_gateway(gw_port, target_url)
        in_ok &= status == 200 and data.get("countryCode") == "IN"
    gw.set_countries(["ZZ"])
    status_zz, _ = await request_via_gateway(gw_port, target_url)
    record("10_country_selection_accuracy", "PASS" if ok_country and us_ok and in_ok and status_zz == 502 else "FAIL",
           f"US={us_ok}, IN={in_ok}, no-proxy ZZ status={status_zz}")
    gw.set_countries(["all"])

    # 11 HTTP forwarding
    status, data = await request_via_gateway(gw_port, target_url)
    record("11_http_forwarding", "PASS" if status == 200 and data.get("path") == "/check" else "FAIL",
           f"status={status}, path={data.get('path')}")

    # 12 HTTPS CONNECT tunnelling (local TCP target, marker upstream)
    reader, writer = await asyncio.open_connection("127.0.0.1", gw_port)
    writer.write(f"CONNECT 127.0.0.1:{target_port} HTTP/1.1\r\nHost: 127.0.0.1:{target_port}\r\n\r\n".encode())
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    connect_ok = b"200" in head.split(b"\r\n", 1)[0]
    if connect_ok:
        writer.write(b"GET /check HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        body = await asyncio.wait_for(reader.read(4096), timeout=10)
        connect_ok = b"200 OK" in body and b"/check" in body
    writer.close()
    record("12_https_connect_tunnelling", "PASS" if connect_ok else "FAIL",
           "CONNECT 200 + tunnelled HTTP response received via local endpoint" if connect_ok else repr(head[:100]))

    # 13/14 SOCKS4 and SOCKS5 upstream
    socks_results = {}
    for version in (4, 5):
        proxy = MarkerSocksProxy(version, "208.67.222.222" if version == 4 else "208.67.220.220", "US")
        await proxy.start()
        add_proxy(storage, "127.0.0.1", proxy.port, f"socks{version}", "US", proxy.exit_ip)
        gw.reload_pool()
        gw.set_countries(["all"])
        gw.set_mode("sticky")
        gw.current = None
        gw.last_ip = ""
        status, data = await request_via_gateway(gw_port, target_url)
        socks_results[f"socks{version}"] = (status, data.get("query"))
        await proxy.stop()
    gw.set_mode("per_connection")
    ok_socks = all(v[0] == 200 for v in socks_results.values())
    record("13_socks4_upstream", "PASS" if socks_results["socks4"][0] == 200 else "FAIL", str(socks_results["socks4"]))
    record("14_socks5_upstream", "PASS" if socks_results["socks5"][0] == 200 else "FAIL", str(socks_results["socks5"]))

    # 15 failed proxy handling / quarantine
    gw.cfg["health"]["max_consecutive_failures"] = 1
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    add_proxy(storage, "127.0.0.1", 9, "http", "US", "80.80.80.80")
    gw.reload_pool()
    gw.set_countries(["all"])
    status, _ = await request_via_gateway(gw_port, target_url, timeout=8)
    dist = storage.health_distribution()
    record("15_failed_proxy_handling", "PASS" if status == 502 and dist.get("quarantined", 0) >= 1 else "FAIL",
           f"status={status}, quarantined={dist.get('quarantined')}")

    # 16 proxy recovery via controlled revalidation
    gw.stop_event.clear()
    config = dict(app.config)
    config["validation_endpoints"] = [{"url": target_url, "type": "generic", "weight": 1}]
    app.config["validation_endpoints"] = config["validation_endpoints"]
    healthy_marker = MarkerHTTPProxy("95.95.95.95", "US")
    await healthy_marker.start()
    key = add_proxy(storage, "127.0.0.1", healthy_marker.port, "http", "US", "95.95.95.95")
    storage.mark_failure(key, 1, 1, "controlled quarantine")
    storage.conn.execute(
        "UPDATE proxies SET quarantine_until='2020-01-01T00:00:00Z' WHERE key=?", (key,)
    )
    storage.conn.commit()
    before = storage.health_distribution().get("quarantined", 0)
    result = await gw.run_health_cycle()
    after = storage.health_distribution().get("quarantined", 0)
    record("16_proxy_recovery", "PASS" if result.get("recovered", 0) >= 1 and after < before else "FAIL",
           f"quarantined {before}->{after}, {result}")
    await healthy_marker.stop()

    # 17 empty pool behaviour
    gw.pool.clear()
    gw.failed_keys.clear()
    status, data = await request_via_gateway(gw_port, target_url)
    record("17_empty_pool_handling", "PASS" if status == 502 else "FAIL",
           f"status={status}, error={str(data.get('error'))[:80]}")

    # 18 timeout handling
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    slow = MarkerHTTPProxy("77.77.77.77", "US", slow=2.5)
    await slow.start()
    add_proxy(storage, "127.0.0.1", slow.port, "http", "US", "77.77.77.77")
    gw.cfg["connect_timeout_seconds"] = 0.4
    gw.reload_pool()
    started = time.monotonic()
    status, _ = await request_via_gateway(gw_port, target_url, timeout=8)
    elapsed = time.monotonic() - started
    record("18_timeout_handling", "PASS" if status == 502 else "FAIL",
           f"status={status}, elapsed={elapsed:.2f}s")
    await slow.stop()
    gw.cfg["connect_timeout_seconds"] = 5.0

    # 19 authentication with hashed credentials
    gw.set_countries(["all"])
    gw.cfg["auth"]["enabled"] = True
    gw.security.auth["enabled"] = True
    gw.security.set_credentials("tester", "S3cretPass!")
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    auth_proxy = MarkerHTTPProxy("66.66.66.66", "US")
    await auth_proxy.start()
    add_proxy(storage, "127.0.0.1", auth_proxy.port, "http", "US", "66.66.66.66")
    gw.reload_pool()
    status_none, _ = await request_via_gateway(gw_port, target_url)
    status_bad, _ = await request_via_gateway(gw_port, target_url, auth="tester:wrong")
    status_ok, _ = await request_via_gateway(gw_port, target_url, auth="tester:S3cretPass!")
    salt = gw.security.auth.get("salt", "")
    digest = gw.security.auth.get("password_hash", "")
    hash_ok = verify_password("S3cretPass!", salt, digest, gw.security.auth.get("iterations", 160000))
    record("19_authentication_and_hashing", "PASS" if status_none == 407 and status_bad == 407 and status_ok == 200 and hash_ok else "FAIL",
           f"none={status_none}, bad={status_bad}, valid={status_ok}, PBKDF2 verified={hash_ok}, plaintext={gw.cfg['auth'].get('password')!r}")

    # 20 IP allowlist rejection
    gw.security.security["ip_allowlist"] = ["203.0.113.0/24"]
    status_blocked, _ = await request_via_gateway(gw_port, target_url, auth="tester:S3cretPass!")
    gw.security.security["ip_allowlist"] = []
    record("20_unauthorized_peer_rejection", "PASS" if status_blocked == 403 else "FAIL",
           f"status={status_blocked}")

    # 21 destination restrictions
    gw.security.security["destination_policy"] = "allowlist"
    gw.security.security["destination_allowlist"] = ["example.invalid:80"]
    status_denied, _ = await request_via_gateway(gw_port, target_url, auth="tester:S3cretPass!")
    gw.security.security["destination_policy"] = "all"
    gw.security.security["destination_allowlist"] = []
    record("21_restricted_destination_policy", "PASS" if status_denied == 403 else "FAIL",
           f"status={status_denied}")

    # 22 health monitoring cycle
    health_result = await gw.run_health_cycle()
    record("22_background_health_monitoring", "PASS" if isinstance(health_result, dict) else "FAIL", str(health_result))

    # 23 pool refresh cycle
    refreshes = {"count": 0}

    async def fake_refresh():
        refreshes["count"] += 1

    gw.refresh_callback = fake_refresh
    await gw.run_pool_refresh_cycle()
    record("23_automatic_pool_refresh", "PASS" if refreshes["count"] == 1 and gw.metrics.last_refresh != "never" else "FAIL",
           f"callback calls={refreshes['count']}, last_refresh={gw.metrics.last_refresh}")

    # 24 graceful shutdown preserving active connection
    sock = socket.create_connection(("127.0.0.1", gw_port), timeout=5)
    sock.sendall(b"CONNECT 127.0.0.1:9 HTTP/1.1\r\nHost: 127.0.0.1:9\r\n\r\n")
    await asyncio.sleep(0.3)
    started = time.monotonic()
    stop_task = asyncio.create_task(gw.stop(grace=2))
    await asyncio.sleep(0.4)
    sock.close()
    await stop_task
    stop_elapsed = time.monotonic() - started
    record("24_graceful_shutdown", "PASS" if not gw.running else "FAIL",
           f"stop waited {stop_elapsed:.2f}s for active connection")

    # 25 restart + persistence
    gw.cfg["auth"]["enabled"] = False
    gw.security.auth["enabled"] = False
    restarted = await gw.start()
    persisted = storage.count_working() >= 1
    record("25_restart_and_persistence", "PASS" if restarted and persisted else "FAIL",
           f"restarted={restarted}, persisted proxies={storage.count_working()}")

    # 26 controlled concurrency benchmarks (reset failure policy first)
    benchmarks = {}
    gw.cfg["health"]["max_consecutive_failures"] = 3
    gw.failed_keys.clear()
    gw.circuits.clear()
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    for server in marker_servers:
        add_proxy(storage, "127.0.0.1", server.port, "http", server.country, server.exit_ip)
    gw.reload_pool()
    gw.set_countries(["all"])
    gw.set_mode("per_connection")
    for workers in (10, 50, 100, 200, 500):
        gw.global_sem = asyncio.Semaphore(max(workers, 600))
        gw.cfg["security"]["max_connections"] = 600
        count = workers
        started = time.monotonic()
        statuses = []

        async def batch():
            status, _ = await request_via_gateway(gw_port, target_url, timeout=20)
            statuses.append(status)

        try:
            await asyncio.gather(*(batch() for _ in range(count)))
            elapsed = time.monotonic() - started
            ok_count = sum(1 for s in statuses if s == 200)
            benchmarks[workers] = {
                "requests": count, "ok": ok_count,
                "seconds": round(elapsed, 2), "rps": round(ok_count / elapsed, 1),
            }
        except OSError as exc:
            benchmarks[workers] = {"status": "BLOCKED", "error": str(exc)[:100]}
    # Correct stress criteria: a benchmark is only a PASS when a sustained
    # success rate is achieved; otherwise report the real rate honestly.
    all_rates = [
        v["ok"] / v["requests"] for v in benchmarks.values() if "ok" in v
    ]
    worst = min(all_rates) if all_rates else 0.0
    bench_status = "PASS" if worst >= 0.95 else ("PARTIAL PASS" if worst >= 0.80 else "FAIL")
    record("26_concurrency_benchmarks", bench_status,
           f"worst success rate={worst:.1%}; " + "; ".join(
               f"{k}:{v.get('ok', v.get('status'))}/{v.get('requests','?')}@{v.get('rps','0')}rps"
               for k, v in sorted(benchmarks.items())
           ))
    DETAILS["benchmarks"] = json.dumps(benchmarks)

    # 27 memory leak check
    gc.collect()
    tracemalloc.start()
    baseline = tracemalloc.take_snapshot()
    for _ in range(200):
        await request_via_gateway(gw_port, target_url)
    gc.collect()
    current = tracemalloc.take_snapshot()
    growth = sum(s.size_diff for s in current.compare_to(baseline, "filename")) / (1024 * 1024)
    tracemalloc.stop()
    record("27_memory_leak_check", "PASS" if growth < 12.0 else "FAIL", f"growth={growth:.2f} MB over 200 requests")

    # 28 file descriptor leak check
    fd_dir = Path("/proc/self/fd")
    before_fd = len(list(fd_dir.iterdir())) if fd_dir.exists() else -1
    for _ in range(120):
        await request_via_gateway(gw_port, target_url)
    await asyncio.sleep(0.5)
    after_fd = len(list(fd_dir.iterdir())) if fd_dir.exists() else -1
    record("28_fd_leak_check", "PASS" if before_fd < 0 or after_fd <= before_fd + 5 else "FAIL",
           f"fds {before_fd} -> {after_fd}")

    # 29 long-duration stability (30 s, controlled local traffic)
    start_time = time.monotonic()
    successes = 0

    async def sustained():
        nonlocal successes
        while time.monotonic() - start_time < 30:
            status, _ = await request_via_gateway(gw_port, target_url, timeout=10)
            if status == 200:
                successes += 1
            await asyncio.sleep(0.1)

    await asyncio.gather(*(sustained() for _ in range(4)))
    record("30_long_duration_stability", "PASS" if successes >= 30 else "FAIL",
           f"30s run, {successes} successful requests, gateway running={gw.running}")

    # 30 output file integrity
    counts = storage.export_all()
    txt_lines = len((WORK / "output" / "working_proxies.txt").read_text().splitlines())
    csv_rows = max(0, len((WORK / "output" / "working_proxies.csv").read_text().splitlines()) - 1)
    json_total = json.loads((WORK / "output" / "working_proxies.json").read_text())["total"]
    ok = txt_lines == csv_rows == json_total == counts["working_proxies.txt"]
    record("29_output_file_integrity", "PASS" if ok else "FAIL",
           f"txt={txt_lines}, csv={csv_rows}, json={json_total}, report={counts['working_proxies.txt']}")

    await gw.stop()
    for server in marker_servers:
        await server.stop()
    await auth_proxy.stop()
    await runner.cleanup()
    app.close()


async def test_tls_listener() -> None:
    import ssl
    runner, target_port = await start_target()
    app = App()
    gw = fresh_gateway(app, free_port())
    gw.cfg["security"]["tls"]["enabled"] = True
    gw.cfg["security"]["tls"]["certfile"] = str(WORK / "tests/fixtures/localhost.crt")
    gw.cfg["security"]["tls"]["keyfile"] = str(WORK / "tests/fixtures/localhost.key")
    marker = MarkerHTTPProxy("123.123.123.123", "US")
    await marker.start()
    add_proxy(app.storage, "127.0.0.1", marker.port, "http", "US", "123.123.123.123")
    started = await gw.start()
    ok = False
    if started:
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            # Use asyncio streams: a blocking ssl.wrap_socket would stall the
            # same event loop that hosts the gateway (test-fixture pitfall).
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    "127.0.0.1", gw.port, ssl=context, server_hostname="localhost"
                ),
                timeout=10,
            )
            writer.write(
                f"GET http://127.0.0.1:{target_port}/check HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()
            response = await asyncio.wait_for(reader.read(8192), timeout=10)
            writer.close()
            ok = b"200 OK" in response and b"/check" in response
        except Exception as exc:  # noqa: BLE001
            ok = False
            print("TLS test error:", type(exc).__name__, exc)
    await gw.stop()
    await marker.stop()
    await runner.cleanup()
    app.close()
    record("31_tls_listener", "PASS" if ok else "FAIL",
           "TLS-wrapped request via gateway returned 200" if ok else "TLS listener did not serve a request")


async def test_security_dns_and_loopback() -> None:
    from proxyhunter.security import AuthManager
    app = App()
    manager = AuthManager(app.config)
    manager.security["destination_policy"] = "deny_private"
    manager.security["allow_loopback"] = False
    manager.security["destination_allowlist"] = []
    private_ip = await manager.destination_allowed_async("10.0.0.1", 80)
    loopback = await manager.destination_allowed_async("localhost", 80)
    public_ip = await manager.destination_allowed_async("1.1.1.1", 80)
    hostname = await manager.destination_allowed_async("example.com", 80)
    manager.security["allow_loopback"] = True
    loopback_allowed = await manager.destination_allowed_async("localhost", 80)
    ok = (
        not private_ip[0] and not loopback[0] and public_ip[0] and hostname[0]
        and loopback_allowed[0]
    )
    record("32_dns_and_loopback_security", "PASS" if ok else "FAIL",
           f"private={private_ip[0]}, loopback-default={loopback[0]}, public={public_ip[0]}, "
           f"hostname={hostname[0]}, loopback-opt-in={loopback_allowed[0]}")
    app.close()


def test_packaged_sources_seeding() -> None:
    """Fresh packaged installs must get real sources, never an empty file."""
    empty = WORK / "sources-empty.json"
    empty.write_text('{"custom": []}\n', encoding="utf-8")
    seeded = load_sources(empty)
    enabled = sum(
        1 for category, entries in seeded.items()
        if not category.startswith("_") and isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict) and entry.get("enabled", True) and entry.get("url")
    )
    rewritten = empty.stat().st_size > 100

    malformed = WORK / "sources-broken.json"
    malformed.write_text('{"custom": [', encoding="utf-8")
    recovered = load_sources(malformed)
    recovered_enabled = sum(
        1 for category, entries in recovered.items()
        if not category.startswith("_") and isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict) and entry.get("enabled", True) and entry.get("url")
    )

    previous = os.environ.get("PROXYHUNTER_HOME")
    override = WORK / "home-override"
    os.environ["PROXYHUNTER_HOME"] = str(override)
    try:
        override_ok = base_dir() == override
    finally:
        if previous is None:
            os.environ.pop("PROXYHUNTER_HOME", None)
        else:
            os.environ["PROXYHUNTER_HOME"] = previous

    ok = enabled > 0 and rewritten and recovered_enabled > 0 and override_ok
    record(
        "33_packaged_sources_seeding",
        "PASS" if ok else "FAIL",
        f"empty->{enabled} enabled (rewritten={rewritten}), "
        f"malformed->{recovered_enabled}, override_dir={override_ok}",
    )


async def main_async() -> None:
    test_syntax()
    test_dependencies()
    test_startup()
    test_regression()
    await test_database_integrity()
    test_database_migration()
    await gateway_tests()
    await test_tls_listener()
    await test_security_dns_and_loopback()
    test_packaged_sources_seeding()


def main() -> None:
    try:
        asyncio.run(main_async())
    except Exception as exc:  # noqa: BLE001
        record("suite_runner", "FAIL", f"{type(exc).__name__}: {exc}")
    counts: dict[str, int] = {}
    for result in RESULTS:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    report = {
        "version": __version__,
        "timestamp": utc_now(),
        "workspace": str(WORK),
        "results": RESULTS,
        "counts": counts,
        "benchmarks": json.loads(DETAILS.get("benchmarks", "{}")),
    }
    target = SRC / "output" / "test_results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("\nSUMMARY:", counts)
    print("report:", target)


if __name__ == "__main__":
    main()
