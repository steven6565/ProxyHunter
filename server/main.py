"""ProxyHunter v4.0.0 centralized backend (FastAPI).

Wraps the existing BackendController and exposes authenticated REST + WebSocket
endpoints.  Heavy discovery/validation/export runs on the server (VPS), not on
the Windows client.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.controller import BackendController, BackendWorker

API_KEY = os.environ.get("PROXYHUNTER_API_KEY", "")
DATA_DIR = Path(os.environ.get("PROXYHUNTER_DATA_DIR", str(ROOT))).expanduser().resolve()
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PROXYHUNTER_HOME", str(DATA_DIR))

controller = BackendController()
worker = BackendWorker(controller)

# Optional CI/dev override; the Windows client never sees this port.
if os.environ.get("PROXYHUNTER_GATEWAY_PORT"):
    controller.config.setdefault("gateway", {})["port"] = int(os.environ["PROXYHUNTER_GATEWAY_PORT"])

app = FastAPI(title="ProxyHunter Backend", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_clients: set[WebSocket] = set()


def require_key(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    return True


def _safe_name(value: Any, default: str = "working_proxies") -> str:
    name = Path(str(value or default)).name.strip()
    return name or default


def _safe_formats(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        value = ["json"]
    formats = [str(item).lower() for item in value if str(item).lower() in ("txt", "csv", "json")]
    return formats or ["json"]


@app.on_event("startup")
async def _startup():
    if controller.config.get("gateway", {}).get("auto_start", True):
        try:
            await controller.gateway_start()
        except Exception:
            pass
    asyncio.create_task(_broadcast_loop())


async def _broadcast_loop():
    while True:
        await asyncio.sleep(1.0)
        if not _clients:
            continue
        payload = json.dumps({"type": "stats", "data": controller.stats()})
        dead = []
        for ws in list(_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)


@app.get("/health")
async def health():
    return {"ok": True, "version": "4.0.0", "backend": "READY"}


@app.get("/api/stats")
async def stats(_: bool = Depends(require_key)):
    data = controller.stats()
    data["countries_count"] = len(controller.countries())
    return data


@app.post("/api/discover")
async def discover(body: dict = {}, _: bool = Depends(require_key)):
    workers = int(body.get("workers", controller.config.get("workers", {}).get("count", 50)))
    controller.config["workers"]["count"] = max(1, min(500, workers))
    controller.resume()
    worker.submit(controller.discover(workers=workers))
    return {"started": True, "workers": workers}


@app.post("/api/check")
async def check(body: dict = {}, _: bool = Depends(require_key)):
    limit = int(body.get("limit", 0) or 0)
    controller.resume()
    worker.submit(controller.check(limit=limit))
    return {"started": True, "limit": limit}


@app.post("/api/refresh")
async def refresh(body: dict = {}, _: bool = Depends(require_key)):
    limit = int(body.get("limit", 200) or 200)
    controller.resume()
    worker.submit(controller.discover_and_check(limit=limit))
    return {"started": True, "limit": limit}


@app.post("/api/stop")
async def stop(_: bool = Depends(require_key)):
    controller.request_stop()
    return {"ok": True}


@app.get("/api/proxies")
async def proxies(country: str = "", protocol: str = "", max_latency: float = 0,
                  working_only: bool = True, limit: int = 0,
                  _: bool = Depends(require_key)):
    if working_only:
        items = controller.proxies(country=country, protocol=protocol,
                                   max_latency=max_latency, limit=limit)
    else:
        items = [item.to_dict() for item in controller.storage.get_all(limit=limit)]
        if country and country != "all":
            items = [item for item in items if item.get("country_code") == country]
        if protocol and protocol != "all":
            items = [item for item in items if item.get("protocol") == protocol]
    return {"proxies": items, "count": len(items)}


@app.get("/api/sources")
async def sources(_: bool = Depends(require_key)):
    return {"sources": controller.sources()}


@app.post("/api/source_set")
async def source_set(body: dict, _: bool = Depends(require_key)):
    return {"ok": controller.set_source(str(body.get("name", "")), bool(body.get("enabled", True)))}


@app.post("/api/source_test")
async def source_test(body: dict, _: bool = Depends(require_key)):
    return await controller.test_source(str(body.get("name", "")))


@app.get("/api/countries")
async def countries(_: bool = Depends(require_key)):
    return {"countries": controller.countries()}


@app.get("/api/capacity")
async def capacity(_: bool = Depends(require_key)):
    return {"capacity": controller.capacity()}


@app.get("/api/rotation_modes")
async def rotation_modes(_: bool = Depends(require_key)):
    return {"modes": list(controller.rotation_modes)}


@app.get("/api/worker_presets")
async def worker_presets(_: bool = Depends(require_key)):
    return {"presets": controller.worker_presets}


@app.get("/api/events")
async def events(_: bool = Depends(require_key)):
    return {"events": controller.events_tail(50)}


@app.get("/api/connectivity")
async def connectivity(_: bool = Depends(require_key)):
    return {"online": controller.connectivity()}


@app.post("/api/export")
async def export(body: dict = {}, _: bool = Depends(require_key)):
    name = _safe_name(body.get("name", "working_proxies"))
    formats = _safe_formats(body.get("formats", body.get("format", "json")))
    address_format = str(body.get("address_format", "ip_port"))
    working_only = bool(body.get("working_only", True))
    limit = int(body.get("limit", 0) or 0)
    proxies = None
    if not working_only:
        items = controller.storage.get_all(limit=limit)
        if not items and controller.last_discovered:
            # Discovery persists a text file; unvalidated rows may not be in
            # SQLite yet.  Export the last discovery batch in that case.
            items = list(controller.last_discovered)
        proxies = [item.to_dict() for item in items]
    files = controller.export(
        str(EXPORT_DIR), name, formats=formats,
        address_format=address_format, proxies=proxies,
    )
    for item in files:
        item["download_url"] = f"/api/download/{item.get('name', '')}"
    return {"files": files, "count": len(files), "working_only": working_only}


@app.get("/api/download/{name}")
async def download(name: str, _: bool = Depends(require_key)):
    safe = _safe_name(name, "")
    if not safe:
        raise HTTPException(status_code=404, detail="file not found")
    candidate = EXPORT_DIR / safe
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(candidate), filename=safe)


@app.post("/api/gateway_start")
async def gateway_start(_: bool = Depends(require_key)):
    ok = await controller.gateway_start()
    return {"ok": bool(ok), "running": controller.gateway.running,
            "gateway": controller.gateway.snapshot()}


@app.post("/api/gateway_stop")
async def gateway_stop(_: bool = Depends(require_key)):
    await controller.gateway_stop()
    return {"ok": True, "running": controller.gateway.running}


@app.post("/api/gateway_restart")
async def gateway_restart(_: bool = Depends(require_key)):
    ok = await controller.gateway_restart()
    return {"ok": bool(ok), "running": controller.gateway.running,
            "gateway": controller.gateway.snapshot()}


@app.post("/api/gateway_countries")
async def gateway_countries(body: dict, _: bool = Depends(require_key)):
    selection = body.get("countries", body.get("country", "all"))
    ok, warning = controller.gateway_select_countries(selection)
    return {"ok": bool(ok), "warning": warning, "country": controller.gateway.country_label}


@app.post("/api/gateway_mode")
async def gateway_mode(body: dict, _: bool = Depends(require_key)):
    ok = controller.gateway_set_mode(str(body.get("mode", "")))
    return {"ok": bool(ok), "mode": controller.gateway.mode}


@app.post("/api/gateway_auth")
async def gateway_auth(body: dict, _: bool = Depends(require_key)):
    controller.gateway_set_credentials(
        str(body.get("username", "")), str(body.get("password", ""))
    )
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    supplied = ws.query_params.get("api_key", "")
    if API_KEY and supplied != API_KEY:
        # Backward-compatible first-message authentication.
        try:
            message = await asyncio.wait_for(ws.receive_text(), timeout=10)
            if message != API_KEY:
                await ws.close(code=4401)
                return
        except Exception:
            await ws.close(code=4401)
            return
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _clients.discard(ws)


if __name__ == "__main__":
    host = os.environ.get("PROXYHUNTER_HOST", "0.0.0.0")
    port = int(os.environ.get("PROXYHUNTER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
