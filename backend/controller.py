"""UI-agnostic backend controller shared by Android and Windows frontends."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections import deque
from typing import Callable, Iterable

from proxyhunter import __version__
from proxyhunter.checker import Checker
from proxyhunter.config import WORKER_PRESETS, load_config, save_config
from proxyhunter.dashboard import Metrics
from proxyhunter.discovery import Discovery
from proxyhunter.gateway import Gateway, ROTATION_MODES
from proxyhunter.geo import GeoResolver
from proxyhunter.models import Proxy
from proxyhunter.resources import ResourceMonitor
from proxyhunter.storage import Storage
from proxyhunter.utils import deduplicate, parse_proxy
from shared.exports import export_proxies

EVENTS = ("stats", "discovery", "validation", "gateway", "export", "error", "log")


class BridgeDashboard:
    """Dashboard interface that forwards messages to UI listeners."""

    def __init__(self, emit: Callable[[str, dict], None]) -> None:
        self.emit = emit

    def log(self, message: str, style: str = "dim") -> None:
        self.emit("log", {"message": message, "style": style})

    def set_phase(self, description: str, total: int | None = None) -> None:
        self.emit("log", {"message": description, "total": total})

    def set_total(self, total: int) -> None:
        self.emit("stats", {"total": total})

    def advance(self, amount: int = 1) -> None:
        self.emit("stats", {"advance": amount})


class BackendController:
    """Owns the existing engine and exposes simple async operations."""

    def __init__(self, on_event: Callable[[str, dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda kind, data: None)
        self.config = load_config()
        self.storage = Storage(self.config)
        self.geo = GeoResolver(self.config, self.storage)
        self.metrics = Metrics()
        self.events: deque[str] = deque(maxlen=20)
        self.resource_monitor = ResourceMonitor()
        self.stop_event = asyncio.Event()
        self.dashboard = BridgeDashboard(self.emit)
        self.gateway = Gateway(self.config, self.storage, self.geo, self.events)
        self.started = time.monotonic()
        self._network_checked = 0.0
        self._network_ok = False
        self.operation = "idle"
        self.progress = 0.0
        self._refresh_callback_set = False

    def emit(self, kind: str, data: dict) -> None:
        if kind in EVENTS:
            self.on_event(kind, data)

    # --------------------------------------------------------------- operations
    async def discover(self) -> list[Proxy]:
        self.operation = "discovery"
        self.progress = 0.0
        self.emit("discovery", {"phase": "start"})
        discovery = Discovery(self.config, self.storage, self.metrics, self.dashboard)
        proxies = await discovery.discover()
        self.progress = 1.0
        self.emit("discovery", {"phase": "done", "found": len(proxies)})
        self.operation = "idle"
        return proxies

    async def check(self, proxies: Iterable[Proxy] | None = None, limit: int = 0) -> list[Proxy]:
        self.operation = "validation"
        self.progress = 0.0
        self.emit("validation", {"phase": "start"})
        if proxies is None:
            targets = self.storage.get_working(
                max_age_hours=float(self.config.get("validation_max_age_hours", 24))
            )
        else:
            targets = list(proxies)
        if limit > 0:
            targets = targets[:limit]
        checker = Checker(self.config, self.storage, self.geo, self.metrics, self.dashboard, self.stop_event)
        results = await checker.check(targets)
        self.storage.export_all()
        self.progress = 1.0
        working = sum(1 for p in results if p.working)
        self.emit("validation", {"phase": "done", "checked": len(results), "working": working})
        self.operation = "idle"
        return results

    async def discover_and_check(self, limit: int = 0) -> dict:
        found = await self.discover()
        results = await self.check(found, limit=limit)
        return {"found": len(found), "checked": len(results), "working": sum(p.working for p in results)}

    def request_stop(self) -> None:
        self.stop_event.set()
        self.emit("log", {"message": "Stop requested"})

    def resume(self) -> None:
        self.stop_event.clear()

    # ------------------------------------------------------------------ reads
    def proxies(self, country: str = "", protocol: str = "", working_only: bool = True,
                max_latency: float = 0, limit: int = 0) -> list[dict]:
        countries = [country] if country and country != "all" else None
        protocols = [protocol] if protocol and protocol != "all" else None
        items = self.storage.get_working(
            protocols=protocols, countries=countries,
            max_age_hours=float(self.config.get("validation_max_age_hours", 24)),
        ) if working_only else []
        if max_latency > 0:
            items = [p for p in items if p.response_time_ms <= max_latency]
        if limit > 0:
            items = items[:limit]
        return [p.to_dict() for p in items]

    def countries(self) -> dict[str, int]:
        return self.gateway.available_countries()

    def capacity(self) -> dict:
        return self.storage.capacity_report(float(self.config.get("validation_max_age_hours", 24)))

    def stats(self) -> dict:
        cpu, ram, used_mb = self.resource_monitor.snapshot()
        snapshot = self.gateway.snapshot()
        snapshot.update({
            "version": __version__,
            "backend": "READY",
            "internet": "ONLINE" if self.connectivity() else "OFFLINE",
            "gateway": "ONLINE" if self.gateway.running else "OFFLINE",
            "discovered": self.metrics.discovered,
            "unique": self.metrics.unique,
            "checked": self.metrics.checked,
            "working": self.storage.count_working(max_age_hours=24),
            "dead": self.metrics.dead,
            "speed": self.metrics.speed(),
            "active_workers": self.metrics.active_workers,
            "avg_latency": self.metrics.avg_latency(),
            "cpu": cpu,
            "ram": ram,
            "ram_mb": used_mb,
            "uptime": int(time.monotonic() - self.started),
            "operation": self.operation,
            "progress": self.progress,
        })
        return snapshot

    def events_tail(self, count: int = 20) -> list[str]:
        return list(self.events)[-count:]

    def connectivity(self) -> bool:
        """Cached, bounded independent internet check (never uses a proxy)."""
        now = time.monotonic()
        if now - self._network_checked < 30:
            return self._network_ok
        self._network_checked = now
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=2.0):
                self._network_ok = True
        except OSError:
            self._network_ok = False
        return self._network_ok

    # --------------------------------------------------------------- exports
    def export(self, directory: str, name: str = "working_proxies", formats: Iterable[str] = ("txt",),
               address_format: str = "ip_port", proxies: Iterable[dict] | None = None) -> list[dict]:
        items = [Proxy.from_dict(d) for d in proxies] if proxies is not None else self.storage.get_working(
            max_age_hours=float(self.config.get("validation_max_age_hours", 24))
        )
        created = export_proxies(items, directory, name, formats, address_format)
        self.emit("export", {"files": created})
        return created

    # --------------------------------------------------------------- gateway
    async def gateway_start(self) -> bool:
        ok = await self.gateway.start()
        self.emit("gateway", {"running": ok})
        return ok

    async def gateway_stop(self) -> None:
        await self.gateway.stop()
        self.emit("gateway", {"running": False})

    async def gateway_restart(self) -> bool:
        ok = await self.gateway.restart()
        self.emit("gateway", {"running": ok})
        return ok

    def gateway_select_countries(self, selection: str | Iterable[str]) -> tuple[bool, str]:
        ok, warning = self.gateway.set_countries(selection)
        self.emit("gateway", {"countries": self.gateway.country_label, "warning": warning})
        return ok, warning

    def gateway_set_mode(self, mode: str) -> bool:
        ok = self.gateway.set_mode(mode)
        self.emit("gateway", {"mode": self.gateway.mode})
        return ok

    def gateway_set_credentials(self, username: str, password: str) -> None:
        self.gateway.security.set_credentials(username, password)

    @property
    def rotation_modes(self) -> tuple[str, ...]:
        return ROTATION_MODES

    @property
    def worker_presets(self) -> dict:
        return dict(WORKER_PRESETS)

    def close(self) -> None:
        self.geo.close()
        self.storage.close()


class BackendWorker:
    """Runs a controller's coroutines on a dedicated background loop."""

    def __init__(self, controller: BackendController) -> None:
        self.controller = controller
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True, name="proxyhunter-backend")
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def shutdown(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
