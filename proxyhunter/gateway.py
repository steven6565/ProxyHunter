"""Rotating proxy gateway (v2.0) for authorized network testing.

One stable local endpoint (``http://127.0.0.1:8080`` by default -- this is
the port used by the CLI, Android service and Windows desktop app) forwards
each new client connection through an eligible, validated upstream proxy.
HTTP absolute-form requests and HTTPS CONNECT tunnels are supported, as are
HTTP, HTTPS (CONNECT), SOCKS4 and SOCKS5 upstreams. There is never a direct-IP
fallback. Loopback destinations are denied unless explicitly allowed.

Security: localhost binding by default; remote binding requires PBKDF2-based
authentication plus an explicit allow_remote_access flag, optional TLS,
IP allowlisting, per-user connection caps and destination policies.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import ssl
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from python_socks.async_.asyncio import Proxy as SocksProxy

from .config import save_config
from .logging_utils import RotatingFileLogger
from .models import Proxy
from .security import AuthManager, TokenBucket

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ROTATION_MODES = (
    "per_connection", "time_based", "round_robin", "random", "sticky", "lowest_latency"
)
COUNTRY_OPTIONS = ("all", "US", "GB", "IN", "DE", "CA", "other")
VERSION = "2.0.0"


def is_loopback(host: str) -> bool:
    if str(host).lower() in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_ts(value: str) -> float:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass
class GatewayMetrics:
    started: float = field(default_factory=time.monotonic)
    active_connections: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rotations: int = 0
    current_ip: str = ""
    total_proxies: int = 0
    healthy_proxies: int = 0
    failed_proxies: int = 0
    quarantined: int = 0
    unique_ips: int = 0
    latency_sum: float = 0.0
    latency_count: int = 0
    last_refresh: str = ""
    last_health: str = ""

    def uptime(self) -> str:
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    def avg_latency(self) -> float:
        return self.latency_sum / self.latency_count if self.latency_count else 0.0

    def snapshot(self, running: bool, bind: str, port: int, country: str, mode: str) -> dict:
        eligible = self.healthy_proxies
        return {
            "version": VERSION,
            "status": "ONLINE" if running else "OFFLINE",
            "endpoint": f"http://{bind}:{port}",
            "country": country,
            "mode": mode,
            "total": self.total_proxies,
            "healthy": eligible,
            "failed": self.failed_proxies,
            "quarantined": self.quarantined,
            "unique_ips": self.unique_ips,
            "active": self.active_connections,
            "current_ip": self.current_ip or "-",
            "latency": self.avg_latency(),
            "success": self.successful_requests,
            "requests_failed": self.failed_requests,
            "rotations": self.rotations,
            "last_refresh": self.last_refresh or "never",
            "last_health": self.last_health or "never",
            "uptime": self.uptime(),
            "capacity_warning": eligible <= 0,
        }


@dataclass
class Upstream:
    proxy: Proxy
    failures: int = 0
    last_used: float = 0.0
    healthy: bool = True
    circuit_open_until: float = 0.0

    @property
    def key(self) -> str:
        return self.proxy.key

    @property
    def ip(self) -> str:
        return self.proxy.host

    @property
    def url(self) -> str:
        return self.proxy.url


class HeadlessDashboard:
    """Minimal dashboard interface for background discovery/validation."""

    def __init__(self, events: deque) -> None:
        self.events = events

    def log(self, message: str, style: str = "dim") -> None:
        self.events.append(f"[pool] {message}")

    def set_phase(self, *args, **kwargs) -> None:
        pass

    def set_total(self, *args, **kwargs) -> None:
        pass

    def advance(self, *args, **kwargs) -> None:
        pass


class Gateway:
    """Async HTTP proxy server with rotating, validated upstream selection."""

    def __init__(self, config: dict, storage, geo, events: deque | None = None) -> None:
        self.config = config
        self.cfg = config.setdefault("gateway", {})
        self.storage = storage
        self.geo = geo
        self.events = events if events is not None else deque(maxlen=12)
        self.metrics = GatewayMetrics()
        self.pool: dict[str, Upstream] = {}
        self.failed_keys: set[str] = set()
        self.countries: set[str] = set()
        self._set_countries_from_config()
        self.mode = str(self.cfg.get("rotation_mode") or "per_connection").lower()
        self.last_ip = ""
        self.cursor = 0
        self.current: Upstream | None = None
        self.last_rotation = 0.0
        self.server: asyncio.AbstractServer | None = None
        self.tasks: list[asyncio.Task] = []
        self.client_tasks: set[asyncio.Task] = set()
        self.stop_event = asyncio.Event()
        self.refresh_callback: Callable[[], Awaitable[None]] | None = None
        self.security = AuthManager(self.config, self.events)
        self.circuits: dict[str, tuple[int, float]] = {}
        self.ssl_context: ssl.SSLContext | None = None
        self.global_sem = asyncio.Semaphore(
            max(1, int((self.cfg.get("security") or {}).get("max_connections", 200)))
        )
        self.rate_bucket = TokenBucket((self.cfg.get("security") or {}).get("rate_limit_per_second", 0))
        self.access_log = RotatingFileLogger(
            Path(__file__).resolve().parent.parent / "output/logs/gateway_access.log"
        )

    def _set_countries_from_config(self) -> None:
        raw = self.cfg.get("country", "all")
        values = [str(x).strip().upper() for x in (raw if isinstance(raw, list) else str(raw).split(",")) if str(x).strip()]
        self.countries = set(values) if values else {"all"}

    # --------------------------------------------------------------- properties
    @property
    def running(self) -> bool:
        return self.server is not None

    @property
    def bind(self) -> str:
        return str(self.cfg.get("bind", "127.0.0.1"))

    @property
    def port(self) -> int:
        return int(self.cfg.get("port", 8080))

    @property
    def country_label(self) -> str:
        return ",".join(sorted(self.countries)) if self.countries else "all"

    def _log(self, message: str) -> None:
        self.events.append(f"[{self.metrics.uptime()}] {message}")
        self.access_log.log("INFO", message)

    def available_countries(self) -> dict[str, int]:
        capacity = self.storage.capacity_report(float((self.cfg.get("health") or {}).get("max_upstream_age_hours", 24)))
        return {code: data["count"] for code, data in capacity["countries"].items()}

    def capacity_warning(self) -> str:
        if not self.countries or "all" in self.countries:
            if not self.pool:
                return "WARNING: no validated upstreams available"
            return ""
        missing = [c for c in sorted(self.countries) if c not in ("other",) and not self._country_candidates(c)]
        if missing:
            return f"WARNING: no recently validated proxy for {', '.join(missing)}"
        return ""

    # ------------------------------------------------------------------ control
    async def start(self) -> bool:
        if self.running:
            self._log("Gateway already running")
            return True
        auth = self.cfg.get("auth") or {}
        if not is_loopback(self.bind):
            if not (
                self.cfg.get("allow_remote_access")
                and auth.get("enabled")
                and auth.get("username")
                and (auth.get("password_hash") or auth.get("password"))
            ):
                self._log("REFUSED: remote bind requires authentication + allow_remote_access")
                return False
        # v3: loopback destinations stay denied unless the user explicitly
        # enables them in config; localhost binding is unrelated to targets.
        self.security.security["allow_loopback"] = bool(
            self.security.security.get("allow_loopback", False)
        )

        tls = (self.cfg.get("security") or {}).get("tls") or {}
        if tls.get("enabled"):
            cert, key = tls.get("certfile"), tls.get("keyfile")
            if not cert or not key or not Path(cert).is_file() or not Path(key).is_file():
                self._log("REFUSED: TLS enabled but certificate/key missing")
                return False
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert, key)
                self.ssl_context = context
            except (OSError, ssl.SSLError) as exc:
                self._log(f"REFUSED: TLS setup failed: {exc}")
                return False

        self.reload_pool()
        self.stop_event = asyncio.Event()
        try:
            self.server = await asyncio.start_server(
                self._handle_client, self.bind, self.port,
                limit=65536, ssl=self.ssl_context,
            )
        except OSError as exc:
            self.server = None
            self._log(f"Failed to bind {self.bind}:{self.port}: {exc}")
            return False
        self.metrics = GatewayMetrics()
        self.reload_pool()
        self.tasks = [
            asyncio.create_task(self._health_loop(), name="gateway-health"),
            asyncio.create_task(self._refresh_loop(), name="gateway-refresh"),
        ]
        self._log(
            f"Gateway ONLINE at http://{self.bind}:{self.port} "
            f"({self.metrics.healthy_proxies} eligible upstreams)"
        )
        return True

    async def stop(self, grace: float = 5.0) -> None:
        if self.server is not None:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self.server = None
        self.stop_event.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        self.tasks = []
        if self.client_tasks:
            _, pending = await asyncio.wait(self.client_tasks, timeout=grace)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self.security.sessions.clear()
        self.current = None
        self.metrics.current_ip = ""
        self._log("Gateway OFFLINE (active connections finished or timed out)")

    async def restart(self) -> bool:
        await self.stop()
        return await self.start()

    def set_countries(self, selection) -> tuple[bool, str]:
        values = []
        if isinstance(selection, (list, tuple, set)):
            values = [str(x).strip().upper() for x in selection if str(x).strip()]
        else:
            values = [str(x).strip().upper() for x in str(selection).replace("|", ",").split(",") if str(x).strip()]
        if not values:
            return False, "no country supplied"
        self.countries = set(values)
        self.cfg["country"] = ",".join(sorted(self.countries))
        save_config(self.config)
        warning = self.capacity_warning()
        self._log(f"Country selection: {self.country_label}{' ' + warning if warning else ''}")
        return True, warning

    def set_country(self, selection: str) -> None:
        """Backward-compatible single-country setter."""
        self.set_countries(selection)

    def set_mode(self, mode: str) -> bool:
        mode = str(mode).lower()
        if mode not in ROTATION_MODES:
            return False
        self.mode = mode
        self.cfg["rotation_mode"] = mode
        save_config(self.config)
        self._log(f"Rotation mode: {mode}")
        return True

    def reset_rotation(self) -> None:
        self.last_ip = ""
        self.current = None
        self.cursor = 0
        self.last_rotation = 0.0
        self._log("Rotation state reset")

    def snapshot(self) -> dict:
        return self.metrics.snapshot(
            self.running, self.bind, self.port, self.country_label, self.mode
        )

    # -------------------------------------------------------------------- pool
    def reload_pool(self) -> None:
        health_cfg = self.cfg.get("health") or {}
        age = float(health_cfg.get("max_upstream_age_hours", 24))
        old = {key: up for key, up in self.pool.items()}
        proxies = self.storage.get_working(max_age_hours=age)
        limit = int(self.cfg.get("max_pool_size", 0) or 0)
        if limit > 0:
            proxies = proxies[:limit]
        pool: dict[str, Upstream] = {}
        now = time.monotonic()
        for proxy in proxies:
            previous = old.get(proxy.key)
            up = Upstream(
                proxy=proxy,
                failures=previous.failures if previous else 0,
                last_used=previous.last_used if previous else 0.0,
                circuit_open_until=previous.circuit_open_until if previous else 0.0,
            )
            pool[proxy.key] = up
        self.pool = pool
        dist = self.storage.health_distribution()
        capacity = self.storage.capacity_report(age)
        self.metrics.total_proxies = len(pool)
        self.metrics.healthy_proxies = len(pool)
        self.metrics.quarantined = int(dist.get("quarantined", 0))
        self.metrics.failed_proxies = int(dist.get("expired", 0)) + len(self.failed_keys)
        self.metrics.unique_ips = int(capacity.get("unique_exit_ips", 0))
        self.metrics.latency_sum = sum(p.response_time_ms for p in proxies)
        self.metrics.latency_count = len(proxies)
        # Drop expired circuits.
        self.circuits = {k: v for k, v in self.circuits.items() if v[1] > now}
        if self.current is not None and self.current.key not in pool:
            self.current = None
            self.metrics.current_ip = ""

    def _country_candidates(self, code: str) -> list[Upstream]:
        code = code.upper()
        if code == "ALL":
            return list(self.pool.values())
        if code == "OTHER":
            major = {"US", "GB", "IN", "DE", "CA"}
            return [u for u in self.pool.values() if u.proxy.country_code.upper() not in major]
        return [u for u in self.pool.values() if u.proxy.country_code.upper() == code]

    def _candidates(self, exclude: set[str] | None = None) -> list[Upstream]:
        now = time.monotonic()
        max_age = float((self.cfg.get("health") or {}).get("max_upstream_age_hours", 24)) * 3600
        items: list[Upstream] = []
        for group in (self._country_candidates(code) for code in (self.countries or {"all"})):
            items.extend(group)
        seen: set[str] = set()
        result: list[Upstream] = []
        for up in items:
            if up.key in seen or not up.healthy or up.key in self.failed_keys:
                continue
            seen.add(up.key)
            if up.circuit_open_until > now:
                continue
            if max_age > 0 and time.time() - _parse_ts(up.proxy.last_checked) > max_age:
                continue
            if exclude and up.key in exclude:
                continue
            result.append(up)
        return result

    def _select(self, exclude: set[str] | None = None) -> Upstream | None:
        candidates = self._candidates(exclude)
        if not candidates:
            self._log(f"No eligible upstream for country: {self.country_label}")
            return None
        selected: Upstream | None = None
        now = time.monotonic()
        interval = max(1, int(self.cfg.get("rotation_seconds", 60)))
        if self.mode == "sticky" and self.current and self.current.key in self.pool and self.current.healthy:
            selected = self.current
        elif self.mode == "time_based" and self.current and now - self.last_rotation < interval \
                and self.current.key in self.pool and self.current.healthy:
            selected = self.current
        elif self.mode == "lowest_latency":
            selected = min(candidates, key=lambda u: u.proxy.response_time_ms)
        elif self.mode == "random":
            selected = random.choice(candidates)
        else:
            candidates.sort(key=lambda u: u.proxy.response_time_ms)
            self.cursor %= len(candidates)
            selected = candidates[self.cursor]
            self.cursor += 1

        if (
            selected is not None
            and self.mode not in ("sticky", "time_based", "lowest_latency")
            and selected.ip == self.last_ip
            and len(candidates) > 1
        ):
            alternatives = [u for u in candidates if u.ip != self.last_ip]
            if alternatives:
                selected = random.choice(alternatives) if self.mode == "random" else alternatives[0]
        if selected is not None:
            changed = self.current is None or selected.key != self.current.key
            self.current = selected
            selected.last_used = now
            self.last_ip = selected.ip
            self.last_rotation = now
            if changed:
                self.metrics.rotations += 1
            self.metrics.current_ip = selected.ip
        return selected

    # ---------------------------------------------------------- upstream tunnel
    async def _connect_upstream(self, upstream: Upstream, host: str, port: int, timeout: float):
        if upstream.proxy.protocol in ("socks4", "socks5"):
            proxy = SocksProxy.from_url(upstream.url)
            sock = await proxy.connect(host, port, timeout=timeout)
            return await asyncio.open_connection(sock=sock)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(upstream.proxy.host, upstream.proxy.port), timeout=timeout
        )
        try:
            request = (
                f"CONNECT {host}:{port} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\nProxy-Connection: Keep-Alive\r\n\r\n"
            ).encode("utf-8", "ignore")
            writer.write(request)
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            status = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not status or (b" 200 " not in status and not status.rstrip().endswith(b"200")):
                raise ConnectionError(f"upstream CONNECT failed: {status[:60]!r}")
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=timeout)
                if line in (b"\r\n", b"\n", b""):
                    break
            return reader, writer
        except Exception:
            writer.close()
            raise

    def _mark_success(self, upstream: Upstream, latency_ms: float) -> None:
        self.storage.mark_success(upstream.key, latency_ms)
        self.circuits.pop(upstream.key, None)
        upstream.failures = 0
        upstream.circuit_open_until = 0.0

    def _mark_failure(self, upstream: Upstream, reason: str) -> None:
        health = self.cfg.get("health") or {}
        upstream.failures += 1
        threshold = max(1, int(health.get("max_consecutive_failures", self.cfg.get("failure_threshold", 3))))
        state = self.storage.mark_failure(
            upstream.key, threshold,
            int(health.get("quarantine_minutes", 15)), reason,
        )
        failures, opened = self.circuits.get(upstream.key, (0, 0.0))
        failures += 1
        if failures >= max(1, int(health.get("circuit_breaker_threshold", 5))):
            base = float(health.get("backoff_base_seconds", 1.0))
            maximum = float(health.get("backoff_max_seconds", 30.0))
            cooldown = min(maximum, base * (2 ** min(failures - 1, 5)))
            opened = time.monotonic() + max(int(health.get("circuit_cooldown_seconds", 60)), cooldown)
            failures = 0
        self.circuits[upstream.key] = (failures, opened)
        upstream.circuit_open_until = opened
        if state == "quarantined":
            self.failed_keys.add(upstream.key)
            self.pool.pop(upstream.key, None)
            self._log(f"Quarantined {upstream.url}: {reason[:80]}")
        else:
            self._log(f"Upstream {upstream.ip} failure ({upstream.failures}/{threshold}): {reason[:70]}")
        self.metrics.quarantined = self.storage.health_distribution().get("quarantined", 0)
        self.metrics.healthy_proxies = len(self.pool)

    # ------------------------------------------------------------ client handling
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        peer = writer.get_extra_info("peername")
        peer_text = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) and len(peer) >= 2 else str(peer)
        user = "anonymous"
        token = ""
        admitted = False
        try:
            try:
                await asyncio.wait_for(self.global_sem.acquire(), timeout=5.0)
            except asyncio.TimeoutError:
                await self._error(writer, 429, "Gateway connection limit reached")
                return
            admitted = True
            if task is not None:
                self.client_tasks.add(task)
            self.metrics.active_connections += 1
            if not self.security.peer_allowed(peer_text):
                await self._error(writer, 403, "Client address not allowed")
                return
            if not self.security.rate_allowed(peer_text):
                await self._error(writer, 429, "Client rate limit exceeded")
                return
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
                return
            if not head:
                return
            lines = head.split(b"\r\n")
            parts = lines[0].decode("utf-8", "replace").split(" ")
            if len(parts) < 3:
                await self._error(writer, 400, "Bad request")
                return
            method, target = parts[0].upper(), parts[1]
            auth_header = next((line.split(b":", 1)[1] for line in lines[1:] if line.lower().startswith(b"proxy-authorization:")), None)
            ok, user, token_or_reason = self.security.authenticate_header(auth_header, peer_text)
            if not ok:
                await self._error(
                    writer, 407, "Proxy Authentication Required",
                    extra=b'Proxy-Authenticate: Basic realm="ProxyHunter"\r\n',
                )
                return
            token = token_or_reason
            if not self.security.reserve_connection(user):
                await self._error(writer, 429, "Per-user connection limit reached")
                return
            if method == "CONNECT":
                await self._handle_connect(target, reader, writer, token)
            elif method in ("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"):
                await self._handle_http(method, target, lines[1:], reader, writer)
            else:
                await self._error(writer, 405, "Method not allowed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.metrics.failed_requests += 1
            self._log(f"Client error: {type(exc).__name__}: {exc}")
            await self._error(writer, 502, "Bad gateway")
        finally:
            self.security.release_connection(user)
            if token:
                self.security.close_session(token)
            if admitted:
                self.metrics.active_connections -= 1
                self.global_sem.release()
            if task is not None:
                self.client_tasks.discard(task)
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    async def _error(writer, code: int, reason: str, extra: bytes = b"", detail: str = "") -> None:
        body = reason.encode()
        response = (
            f"HTTP/1.1 {code} {reason}\r\n"
            + extra.decode("utf-8", "ignore")
            + (f"X-ProxyHunter-Reason: {detail[:120]}\r\n" if detail else "")
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode() + body
        try:
            writer.write(response)
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass

    async def _tunnel_with_retry(self, host: str, port: int):
        attempts = 1 + max(0, min(4, int(self.cfg.get("max_retries", 2))))
        timeout = max(1.0, min(60.0, float(self.cfg.get("connect_timeout_seconds", 5))))
        last_error = "no eligible upstream"
        tried: set[str] = set()
        for _ in range(attempts):
            upstream = self._select(exclude=tried)
            if upstream is None:
                raise ConnectionError("No eligible validated upstream proxy for the selected country")
            tried.add(upstream.key)
            start = time.perf_counter()
            try:
                reader, writer = await self._connect_upstream(upstream, host, port, timeout)
                latency = (time.perf_counter() - start) * 1000
                self._mark_success(upstream, latency)
                self.metrics.successful_requests += 1
                return upstream, reader, writer
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                self._mark_failure(upstream, last_error)
        raise ConnectionError(f"All upstream attempts failed: {last_error[:120]}")

    async def _handle_connect(self, target: str, reader, writer, token: str) -> None:
        target = target.strip()
        if target.startswith("[") and "]" in target:
            host = target[1:].split("]", 1)[0]
            port_text = target.split("]:", 1)[-1]
        elif ":" in target:
            host, port_text = target.rsplit(":", 1)
        else:
            host, port_text = target, "443"
        try:
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError:
            await self._error(writer, 400, "Invalid CONNECT target")
            return
        allowed, reason = await self.security.destination_allowed_async(host, port)
        if not allowed:
            await self._error(writer, 403, "Destination denied", detail=reason)
            return
        upstream, up_reader, up_writer = await self._tunnel_with_retry(host, port)
        try:
            extra = f"Proxy-Authentication-Info: Bearer {token}\r\n" if token else ""
            writer.write(b"HTTP/1.1 200 Connection Established\r\n" + extra.encode() + b"\r\n")
            await writer.drain()
            self._log(f"CONNECT {host}:{port} via {upstream.url}")
            await self._relay(reader, writer, up_reader, up_writer)
        finally:
            up_writer.close()

    async def _handle_http(self, method: str, target: str, headers: list[bytes], reader, writer) -> None:
        parsed = urlparse(target)
        if parsed.scheme not in ("", "http"):
            await self._error(writer, 400, "Use CONNECT for HTTPS")
            return
        if parsed.hostname:
            host, port = parsed.hostname, parsed.port or 80
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
        else:
            host_header = next(
                (line.split(b":", 1)[1].strip().decode("utf-8", "replace")
                 for line in headers if line.lower().startswith(b"host:")), ""
            )
            host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
            port = int(host_header.rsplit(":", 1)[1]) if ":" in host_header else 80
            path = target
        if not host:
            await self._error(writer, 400, "Missing host")
            return
        allowed, reason = await self.security.destination_allowed_async(host, port)
        if not allowed:
            await self._error(writer, 403, "Destination denied", detail=reason)
            return
        upstream, up_reader, up_writer = await self._tunnel_with_retry(host, port)
        try:
            clean = [
                line for line in headers
                if not line.lower().startswith((b"proxy-authorization:", b"proxy-connection:"))
            ]
            if not any(line.lower().startswith(b"host:") for line in clean):
                clean.insert(0, f"Host: {host}:{port}".encode())
            up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode() + b"\r\n".join(clean) + b"\r\n\r\n")
            await up_writer.drain()
            self._log(f"{method} {host}{path[:40]} via {upstream.url}")
            await self._relay(reader, writer, up_reader, up_writer)
        finally:
            up_writer.close()

    @staticmethod
    async def _copy(reader, writer) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError, OSError):
            pass

    async def _relay(self, client_reader, client_writer, up_reader, up_writer) -> None:
        tasks = {
            asyncio.create_task(self._copy(client_reader, up_writer)),
            asyncio.create_task(self._copy(up_reader, client_writer)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await up_writer.drain()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- health / refresh
    async def run_health_cycle(self) -> dict:
        """Revalidate quarantined and sampled active proxies without touching connections."""
        from .checker import Checker
        from .dashboard import Metrics
        from .utils import deduplicate

        health = self.cfg.get("health") or {}
        quarantine = self.storage.get_quarantined(limit=int(health.get("recovery_batch_size", 20)))
        sample_size = max(1, int(self.cfg.get("health_batch_size", 50)) - len(quarantine))
        active = [up.proxy for up in list(self.pool.values())[:sample_size]]
        batch = deduplicate([*quarantine, *active])
        if not batch:
            self.metrics.last_health = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return {"checked": 0}
        cfg = dict(self.config)
        cfg["max_proxies_to_check"] = len(batch)
        cfg["protocol_filter"] = []
        cfg["country_filter"] = []
        checker = Checker(cfg, self.storage, self.geo, Metrics(), HeadlessDashboard(self.events), self.stop_event)
        checker.remove_dead = False
        results = await checker.check(batch)
        recovered = 0
        failed = 0
        for proxy in results:
            if proxy.working:
                self.storage.recover_proxy(proxy.key)
                self.circuits.pop(proxy.key, None)
                recovered += 1
            else:
                self.storage.mark_failure(
                    proxy.key,
                    int(health.get("max_consecutive_failures", 3)),
                    int(health.get("quarantine_minutes", 15)),
                    "health check failed",
                )
                failed += 1
        self.reload_pool()
        self.metrics.last_health = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.events.append(f"[health] checked={len(results)} recovered={recovered} failed={failed}")
        return {"checked": len(results), "recovered": recovered, "failed": failed}

    async def run_pool_refresh_cycle(self) -> None:
        if self.refresh_callback is not None:
            await self.refresh_callback()
        self.storage.prune_expired(int((self.config.get("refresh_mode") or {}).get("remove_expired_hours", 24)))
        self.storage.export_all()
        self.reload_pool()
        self.metrics.last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.events.append("[pool] discovery + validation refresh complete")

    async def _health_loop(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=max(1, int(self.cfg.get("health_check_minutes", 5))) * 60,
                )
                break
            except asyncio.TimeoutError:
                pass
            if self.stop_event.is_set():
                break
            try:
                await self.run_health_cycle()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.events.append(f"[health] backoff {backoff:.0f}s: {type(exc).__name__}: {exc}")
                await asyncio.sleep(min(backoff, 30))
                backoff = min(30.0, backoff * 2)

    async def _refresh_loop(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=max(1, int(self.cfg.get("pool_refresh_minutes", 15))) * 60,
                )
                break
            except asyncio.TimeoutError:
                pass
            if self.stop_event.is_set():
                break
            try:
                await self.run_pool_refresh_cycle()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.events.append(f"[pool] backoff {backoff:.0f}s: {type(exc).__name__}: {exc}")
                await asyncio.sleep(min(backoff, 30))
                backoff = min(30.0, backoff * 2)
