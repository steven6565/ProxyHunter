"""High-speed asynchronous proxy validation engine."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Iterable

import aiohttp
from aiohttp_socks import ProxyConnector

from .models import Proxy, utc_now
from .net import configure_ca_bundle, make_ssl_context
from .utils import is_public_ip

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Android/Chaquopy and frozen Windows builds may lack a system trust store.
configure_ca_bundle()


class RateLimiter:
    """Simple async token bucket used to respect validation endpoint limits."""

    def __init__(self, rate: float) -> None:
        self.rate = max(0.0, float(rate))
        self._tokens = self.rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.rate <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.rate, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait)


class Checker:
    def __init__(self, config, storage, geo, metrics, dashboard, stop_event: asyncio.Event) -> None:
        self.config = config
        self.storage = storage
        self.geo = geo
        self.metrics = metrics
        self.dashboard = dashboard
        self.stop_event = stop_event
        self.workers = max(1, int(config.get("workers", {}).get("count", 50)))
        self.semaphore = asyncio.Semaphore(self.workers)
        self.limiter = RateLimiter(config.get("rate_limit_per_second", 15))
        self.endpoints = self._build_endpoints(config.get("validation_endpoints") or [])
        self.session: aiohttp.ClientSession | None = None
        # Gateway health cycles keep dead rows for quarantine/recovery instead
        # of physically deleting them.
        self.remove_dead = True

    @staticmethod
    def _build_endpoints(endpoints: list) -> list[dict]:
        pool: list[dict] = []
        for endpoint in endpoints:
            if not isinstance(endpoint, dict) or not endpoint.get("url"):
                continue
            weight = max(1, min(10, int(endpoint.get("weight", 1))))
            pool.extend([endpoint] * weight)
        return pool or [{"url": "https://api.ipify.org?format=json", "type": "ipify", "weight": 1}]

    def _pick_endpoint(self) -> dict:
        return random.choice(self.endpoints)

    # --------------------------------------------------------------- entry point
    async def check(self, proxies: Iterable[Proxy]) -> list[Proxy]:
        targets = list(proxies)
        allowed = set(self.config.get("protocol_filter") or [])
        if allowed:
            targets = [p for p in targets if p.protocol in allowed]
        countries = set(self.config.get("country_filter") or [])
        if countries:
            targets = [p for p in targets if p.country_code in countries]
        limit = int(self.config.get("max_proxies_to_check", 0) or 0)
        if limit > 0:
            targets = targets[:limit]
        if not targets:
            self.dashboard.log("No proxies to check", "yellow")
            return []

        self.metrics.reset_check_counters()
        self.dashboard.set_phase(f"[cyan]Validating {len(targets)} proxies…", total=len(targets))
        timeout = aiohttp.ClientTimeout(
            total=float(self.config.get("timeout_seconds", 8)),
            connect=float(self.config.get("connect_timeout_seconds", 5)),
        )
        connector = aiohttp.TCPConnector(
            limit=self.workers * 2, ttl_dns_cache=300, ssl=make_ssl_context()
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        results: list[Proxy] = []
        buffer: list[Proxy] = []
        tasks = [asyncio.create_task(self._check_one(proxy)) for proxy in targets]

        try:
            for future in asyncio.as_completed(tasks):
                if self.stop_event.is_set():
                    self.dashboard.log("Shutdown requested – cancelling pending checks", "yellow")
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    break
                result = await future
                if result is None:
                    continue
                results.append(result)
                buffer.append(result)
                self.metrics.mark_checked(result)
                self.dashboard.advance(1)
                if len(buffer) >= 25:
                    self.storage.upsert_results(buffer, remove_dead=self.remove_dead)
                    buffer.clear()
        finally:
            if buffer:
                self.storage.upsert_results(buffer, remove_dead=self.remove_dead)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.session is not None:
                await self.session.close()
                self.session = None

        working = [p for p in results if p.working]
        missing_geo = [p.exit_ip for p in working if not p.country_code and p.exit_ip]
        if missing_geo and self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(ssl=make_ssl_context()),
            )
        if missing_geo:
            geo_map = await self.geo.resolve_batch(missing_geo, self.session)
            changed = []
            for p in working:
                if p.exit_ip in geo_map:
                    self._apply_geo(p, geo_map[p.exit_ip])
                    changed.append(p)
            if changed:
                self.storage.upsert_results(changed)
        if self.session is not None:
            await self.session.close()
            self.session = None

        self.dashboard.log(
            f"Validation complete: {len(working)} working / {len(results)} checked",
            "green" if working else "yellow",
        )
        return results

    # ------------------------------------------------------------ per-proxy flow
    async def _check_one(self, proxy: Proxy) -> Proxy | None:
        if self.stop_event.is_set():
            return None
        try:
            async with self.semaphore:
                await self.limiter.acquire()
                if self.stop_event.is_set():
                    return None
                self.metrics.active_workers += 1
                try:
                    return await self._evaluate(proxy)
                finally:
                    self.metrics.active_workers -= 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            proxy.working = False
            proxy.error = f"{type(exc).__name__}: {exc}"
            proxy.last_checked = utc_now()
            return proxy

    async def _evaluate(self, proxy: Proxy) -> Proxy:
        # Never connect to private/resolved-internal addresses.
        if not is_public_ip(proxy.host):
            try:
                infos = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(proxy.host, proxy.port, type=1),
                    timeout=3.0,
                )
                addresses = {info[4][0] for info in infos}
            except Exception as exc:  # noqa: BLE001
                proxy.error = f"DNS resolution failed: {exc}"
                proxy.last_checked = utc_now()
                return proxy
            if not addresses or not any(is_public_ip(ip) for ip in addresses):
                proxy.error = "host resolves to a private/reserved address"
                proxy.last_checked = utc_now()
                return proxy

        attempts = int(self.config.get("retries", 1)) + 1
        last_error = "unknown error"
        api_data: dict | None = None
        exit_ip = ""
        elapsed_ms = 0.0

        for attempt in range(attempts):
            if self.stop_event.is_set():
                break
            endpoint = self._pick_endpoint()
            start = time.perf_counter()
            try:
                payload = await self._probe(proxy, endpoint)
                exit_ip, api_data = self._parse_payload(endpoint, payload)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                if not is_public_ip(exit_ip):
                    raise ValueError(f"endpoint returned a non-public IP: {exit_ip}")
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                last_error = f"{type(exc).__name__}: {exc}"

        if exit_ip and is_public_ip(exit_ip):
            proxy.working = True
            proxy.response_time_ms = round(elapsed_ms, 2)
            proxy.exit_ip = exit_ip
            proxy.error = ""
            self._apply_geo(proxy, api_data)
            self.dashboard.log(f"OK {proxy.url} {proxy.response_time_ms:.0f}ms", "green")
        else:
            proxy.working = False
            proxy.response_time_ms = round(elapsed_ms, 2)
            proxy.error = last_error[:180]
        proxy.last_checked = utc_now()
        return proxy

    def _apply_geo(self, proxy: Proxy, api_data: dict | None) -> None:
        geo = self.geo.resolve(proxy.exit_ip, api_data)
        if geo:
            proxy.country = geo.get("country", "") or proxy.country
            proxy.country_code = geo.get("country_code", "") or proxy.country_code
            proxy.city = geo.get("city", "") or proxy.city
            proxy.isp = geo.get("isp", "") or proxy.isp

    # ---------------------------------------------------------------- transport
    async def _probe(self, proxy: Proxy, endpoint: dict) -> str:
        url = str(endpoint.get("url"))
        # Free lists label an HTTP CONNECT proxy as "https"; the transport to
        # the proxy itself is still plain HTTP in aiohttp.
        if proxy.protocol in ("http", "https"):
            if self.session is None:
                raise RuntimeError("checker session is not initialised")
            async with self.session.get(url, proxy=f"http://{proxy.address}") as resp:
                body = await resp.text(errors="replace")
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} from validation endpoint")
                return body

        connector = ProxyConnector.from_url(proxy.url)
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=float(self.config.get("timeout_seconds", 8)),
                connect=float(self.config.get("connect_timeout_seconds", 5)),
            ),
        )
        try:
            async with session.get(url) as resp:
                body = await resp.text(errors="replace")
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} from validation endpoint")
                return body
        finally:
            await session.close()

    @staticmethod
    def _parse_payload(endpoint: dict, body: str) -> tuple[str, dict | None]:
        kind = str(endpoint.get("type", "generic")).lower()
        if kind in ("ipapi", "ip-api"):
            data = json.loads(body)
            if not isinstance(data, dict) or str(data.get("status", "")).lower() != "success":
                raise ValueError("ip-api lookup failed")
            ip = str(data.get("query") or "")
            return ip, data
        if kind == "ipify":
            try:
                data = json.loads(body)
                ip = str(data.get("ip", "")) if isinstance(data, dict) else str(data)
            except (json.JSONDecodeError, ValueError):
                ip = body.strip()
            return ip, None
        # Generic endpoint such as httpbin / icanhazip.
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                ip = str(data.get("origin") or data.get("ip") or "")
                if ip:
                    return ip.split(",")[0].strip(), data if "countryCode" in data else None
        except (json.JSONDecodeError, ValueError):
            pass
        match = IP_RE.search(body or "")
        return (match.group(0) if match else ""), None
