"""Remote backend client used by the lightweight Windows EXE (v4.0.0).

Mimics the public surface of BackendController so the desktop UI can talk to a
centralized VPS backend instead of running discovery/validation locally.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import aiohttp

CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / "ProxyHunter" / "connection.json"


def load_connection() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_connection(url: str, api_key: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"url": url.rstrip("/"), "api_key": api_key}), encoding="utf-8")


class RemoteBackendController:
    def __init__(self, on_event=None, url: str = "", api_key: str = ""):
        self.on_event = on_event or (lambda k, d: None)
        conn = load_connection()
        self.base_url = (url or conn.get("url", "")).rstrip("/")
        self.api_key = api_key or conn.get("api_key", "")
        self.config = {"workers": {"count": 50}, "timeout_seconds": 8, "auto_update": True, "auto_export": False}
        self.started = __import__("time").monotonic()
        self.operation = "idle"
        self.progress = 0.0
        self._last_stats = {}

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def _get(self, path):
        async with aiohttp.ClientSession() as s:
            async with s.get(self.base_url + path, headers=self._headers(), timeout=30) as r:
                return await r.json()

    async def _post(self, path, body=None):
        async with aiohttp.ClientSession() as s:
            async with s.post(self.base_url + path, json=body or {}, headers=self._headers(), timeout=60) as r:
                return await r.json()

    async def gateway_start(self):
        try:
            await self._post("/api/gateway_start")
        except Exception:
            pass
        return True

    async def gateway_stop(self):
        try:
            await self._post("/api/gateway_stop")
        except Exception:
            pass

    async def gateway_restart(self):
        await self.gateway_stop()
        return await self.gateway_start()

    async def discover(self, workers=None):
        if workers:
            self.config["workers"]["count"] = workers
        self.operation = "discovery"
        await self._post("/api/discover", {"workers": workers or self.config["workers"]["count"]})
        return []

    async def check(self, proxies=None, limit=0):
        self.operation = "validation"
        await self._post("/api/check", {"limit": limit})
        return []

    async def discover_and_check(self, limit=0):
        await self._post("/api/refresh", {"limit": limit})
        return {"found": 0, "checked": 0, "working": 0}

    def request_stop(self):
        try:
            asyncio.get_event_loop().create_task(self._post("/api/stop"))
        except Exception:
            pass

    def stats(self):
        try:
            self._last_stats = asyncio.get_event_loop().run_until_complete(self._get("/api/stats")) if False else self._last_stats
        except Exception:
            pass
        return self._last_stats or {"backend": "CONNECTING", "version": "4.0.0", "discovered": 0, "working": 0, "checked": 0, "dead": 0, "unique": 0, "active_workers": 0, "configured_workers": self.config["workers"]["count"], "avg_latency": 0, "progress": 0, "operation": self.operation, "gateway": "-", "internet": "-", "status": "CONNECTING", "sources_enabled": 0, "logs": []}

    async def refresh_stats(self):
        try:
            self._last_stats = await self._get("/api/stats")
        except Exception as exc:
            self._last_stats = {"error": str(exc), "backend": "ERROR"}

    def sources(self):
        try:
            import asyncio as _a
            loop = _a.new_event_loop()
            data = loop.run_until_complete(self._get("/api/sources"))
            loop.close()
            return data.get("sources", [])
        except Exception:
            return []

    def set_source(self, name, enabled):
        try:
            import asyncio as _a
            loop = _a.new_event_loop()
            loop.run_until_complete(self._post("/api/source_set", {"name": name, "enabled": enabled}))
            loop.close()
            return True
        except Exception:
            return False

    async def test_source(self, name):
        return await self._post("/api/source_test", {"name": name})

    def proxies(self, country="", protocol="", working_only=True, max_latency=0, limit=0):
        try:
            import asyncio as _a
            loop = _a.new_event_loop()
            data = loop.run_until_complete(self._get(f"/api/proxies?country={country}&protocol={protocol}&max_latency={max_latency}"))
            loop.close()
            return data.get("proxies", [])
        except Exception:
            return []

    def countries(self):
        return {}

    def capacity(self):
        return {}

    def export(self, directory, name="working_proxies", formats=("txt",), address_format="ip_port", proxies=None):
        try:
            import asyncio as _a
            loop = _a.new_event_loop()
            res = loop.run_until_complete(self._post("/api/export", {"directory": directory, "name": name, "format": (formats[0] if formats else "json")}))
            loop.close()
            return res.get("files", [])
        except Exception:
            return []

    @property
    def rotation_modes(self):
        return ("per_connection",)

    @property
    def gateway(self):
        return _RemoteGateway(self)

    def close(self):
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
                import asyncio
                result = asyncio.run(coroutine)
                future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                future.set_exception(exc)

        import threading
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
        return {"status": s.get("gateway", "-"), "endpoint": s.get("endpoint", "remote"), "country": s.get("country", "all"), "mode": s.get("mode", "-"), "healthy": s.get("healthy", 0), "unique_ips": s.get("unique_ips", 0), "active": s.get("active", 0), "success": s.get("success", 0), "failed": s.get("failed", 0), "current_ip": s.get("current_ip", "-"), "latency": s.get("latency", 0)}

    @property
    def running(self):
        return (self.ctrl._last_stats or {}).get("gateway") == "ONLINE"

    async def start(self):
        return True

    async def stop(self):
        pass

    async def restart(self):
        return True

    def set_countries(self, selection):
        return True, ""

    def set_mode(self, mode):
        return True

    def set_credentials(self, u, p):
        pass

    def available_countries(self):
        return {}
PY