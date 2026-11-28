"""Remote backend client used by the lightweight Windows EXE (v4.0.0).

Mimics the public surface of ``BackendController`` so the desktop UI can talk
to a centralized VPS backend instead of running discovery/validation locally.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import aiohttp

from .connection_store import load_connection, save_connection

DEFAULT_ROTATION_MODES = (
    "per_connection", "time_based", "round_robin", "random", "sticky", "lowest_latency",
)


class RemoteBackendController:
    def __init__(self, on_event=None, url: str = "", api_key: str = ""):
        self.on_event = on_event or (lambda k, d: None)
        conn = load_connection()
        env_url = os.environ.get("PROXYHUNTER_BACKEND_URL", "").strip()
        self.base_url = (url or env_url or conn.get("url", "")).rstrip("/")
        self.api_key = api_key or (
            os.environ.get("PROXYHUNTER_API_KEY", "") if env_url else conn.get("api_key", "")
        )
        self.config = {
            "workers": {"count": 50},
            "timeout_seconds": 8,
            "auto_update": True,
            "auto_export": False,
        }
        self.started = __import__("time").monotonic()
        self.operation = "idle"
        self.progress = 0.0
        self._last_stats: dict = {}

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _get(self, path: str, timeout: float = 15) -> dict:
        if not self.base_url:
            raise RuntimeError("backend URL is not configured")
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(self.base_url + path, headers=self._headers()) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"HTTP {response.status}: {text[:200]}")
                return await response.json()

    async def _post(self, path: str, body: dict | None = None, timeout: float = 30) -> dict:
        if not self.base_url:
            raise RuntimeError("backend URL is not configured")
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(self.base_url + path, json=body or {},
                                    headers=self._headers()) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"HTTP {response.status}: {text[:200]}")
                return await response.json()

    @staticmethod
    def _run_sync(coroutine, timeout: float = 20):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(asyncio.wait_for(coroutine, timeout=timeout))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                pass
            loop.close()

    # -------------------------------------------------------------- controls
    async def gateway_start(self) -> bool:
        try:
            data = await self._post("/api/gateway_start", timeout=20)
            return bool(data.get("ok", data.get("running", True)))
        except Exception:  # noqa: BLE001
            return False

    async def gateway_stop(self) -> None:
        try:
            await self._post("/api/gateway_stop", timeout=20)
        except Exception:  # noqa: BLE001
            pass

    async def gateway_restart(self) -> bool:
        try:
            data = await self._post("/api/gateway_restart", timeout=30)
            return bool(data.get("ok", data.get("running", True)))
        except Exception:  # noqa: BLE001
            return False

    def gateway_select_countries(self, selection) -> tuple[bool, str]:
        try:
            data = self._run_sync(self._post("/api/gateway_countries",
                                             {"countries": selection}, timeout=15))
            return bool(data.get("ok")), str(data.get("warning", ""))
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    def gateway_set_mode(self, mode: str) -> bool:
        try:
            data = self._run_sync(self._post("/api/gateway_mode", {"mode": mode}, timeout=15))
            return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def gateway_set_credentials(self, username: str, password: str) -> None:
        try:
            self._run_sync(self._post("/api/gateway_auth",
                                      {"username": username, "password": password}, timeout=15))
        except Exception:  # noqa: BLE001
            pass

    async def discover(self, workers=None):
        if workers:
            self.config["workers"]["count"] = workers
        self.operation = "discovery"
        await self._post("/api/discover", {"workers": workers or self.config["workers"]["count"]},
                         timeout=15)
        return []

    async def check(self, proxies=None, limit=0):
        self.operation = "validation"
        await self._post("/api/check", {"limit": limit}, timeout=15)
        return []

    async def discover_and_check(self, limit=0):
        await self._post("/api/refresh", {"limit": limit}, timeout=15)
        return {"found": 0, "checked": 0, "working": 0}

    def request_stop(self) -> None:
        def _send():
            try:
                asyncio.run(self._post("/api/stop", timeout=10))
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_send, daemon=True).start()

    # ----------------------------------------------------------------- reads
    def stats(self) -> dict:
        return self._last_stats or {
            "backend": "CONNECTING", "version": "4.0.0", "discovered": 0,
            "working": 0, "checked": 0, "dead": 0, "unique": 0,
            "active_workers": 0, "configured_workers": self.config["workers"]["count"],
            "avg_latency": 0, "progress": 0, "operation": self.operation,
            "gateway": "-", "internet": "-", "status": "CONNECTING",
            "sources_enabled": 0, "countries_count": 0, "logs": [],
        }

    async def refresh_stats(self) -> None:
        try:
            self._last_stats = await self._get("/api/stats", timeout=10)
        except Exception as exc:  # noqa: BLE001
            self._last_stats = {"error": str(exc), "backend": "ERROR", "gateway": "-"}

    def sources(self) -> list[dict]:
        try:
            data = self._run_sync(self._get("/api/sources"), timeout=15)
            return data.get("sources", [])
        except Exception:  # noqa: BLE001
            return []

    def set_source(self, name, enabled) -> bool:
        try:
            data = self._run_sync(self._post("/api/source_set",
                                             {"name": name, "enabled": enabled}, timeout=15))
            return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            return False

    async def test_source(self, name):
        return await self._post("/api/source_test", {"name": name}, timeout=20)

    def proxies(self, country="", protocol="", working_only=True, max_latency=0, limit=0) -> list[dict]:
        query = urllib.parse.urlencode({
            "country": country, "protocol": protocol,
            "working_only": str(bool(working_only)).lower(),
            "max_latency": max_latency, "limit": limit,
        })
        try:
            data = self._run_sync(self._get(f"/api/proxies?{query}"), timeout=20)
            return data.get("proxies", [])
        except Exception:  # noqa: BLE001
            return []

    def countries(self) -> dict:
        try:
            data = self._run_sync(self._get("/api/countries"), timeout=10)
            return data.get("countries", {})
        except Exception:  # noqa: BLE001
            return {}

    def capacity(self) -> dict:
        try:
            data = self._run_sync(self._get("/api/capacity"), timeout=10)
            return data.get("capacity", {})
        except Exception:  # noqa: BLE001
            return {}

    # --------------------------------------------------------------- exports
    def export(self, directory, name="working_proxies", formats=("txt",),
               address_format="ip_port", proxies=None) -> list[dict]:
        """Ask the server to export, then download every file locally."""
        if isinstance(formats, str):
            formats = [formats]
        formats = [str(item) for item in formats if str(item) in ("txt", "csv", "json")]
        if not formats:
            formats = ["json"]
        try:
            data = self._run_sync(self._post("/api/export", {
                "name": name,
                "formats": formats,
                "address_format": address_format,
                "working_only": proxies is None,
            }, timeout=60), timeout=75)
        except Exception:  # noqa: BLE001
            return []
        files = data.get("files", [])
        root = Path(directory).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        downloaded: list[dict] = []
        for item in files:
            filename = Path(str(item.get("name", ""))).name
            if not filename:
                continue
            destination = root / filename
            try:
                url = self.base_url + "/api/download/" + urllib.parse.quote(filename)
                request = urllib.request.Request(url, headers={"X-API-Key": self.api_key})
                with urllib.request.urlopen(request, timeout=60) as response:
                    destination.write_bytes(response.read())
                entry = dict(item)
                entry["path"] = str(destination)
                entry["size_bytes"] = destination.stat().st_size
                downloaded.append(entry)
            except Exception:  # noqa: BLE001
                continue
        return downloaded

    @property
    def rotation_modes(self) -> tuple[str, ...]:
        try:
            data = self._run_sync(self._get("/api/rotation_modes"), timeout=5)
            modes = tuple(data.get("modes", ()))
            return modes or DEFAULT_ROTATION_MODES
        except Exception:  # noqa: BLE001
            return DEFAULT_ROTATION_MODES

    @property
    def gateway(self):
        return _RemoteGateway(self)

    def close(self) -> None:
        pass


class RemoteBackendWorker:
    """Runs remote controller coroutines on a background thread."""

    def __init__(self, controller):
        self.controller = controller

    def submit(self, coroutine):
        import concurrent.futures

        future = concurrent.futures.Future()

        def _runner():
            try:
                result = asyncio.run(coroutine)
                future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                future.set_exception(exc)

        threading.Thread(target=_runner, daemon=True).start()
        return future

    def shutdown(self):
        pass


class _RemoteGateway:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.bind = "remote"
        self.port = 0

    def snapshot(self):
        s = self.ctrl._last_stats or {}
        return {
            "status": s.get("gateway", "-"), "endpoint": s.get("endpoint", "remote"),
            "country": s.get("country", "all"), "mode": s.get("mode", "-"),
            "healthy": s.get("healthy", 0), "unique_ips": s.get("unique_ips", 0),
            "active": s.get("active", 0), "success": s.get("success", 0),
            "failed": s.get("failed", 0), "current_ip": s.get("current_ip", "-"),
            "latency": s.get("latency", 0),
        }

    @property
    def running(self):
        return (self.ctrl._last_stats or {}).get("gateway") == "ONLINE"

    async def start(self):
        return await self.ctrl.gateway_start()

    async def stop(self):
        await self.ctrl.gateway_stop()

    async def restart(self):
        return await self.ctrl.gateway_restart()

    def set_countries(self, selection):
        return self.ctrl.gateway_select_countries(selection)

    def set_mode(self, mode):
        return self.ctrl.gateway_set_mode(mode)

    def set_credentials(self, u, p):
        self.ctrl.gateway_set_credentials(u, p)

    def available_countries(self):
        return self.ctrl.countries()
