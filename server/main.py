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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.controller import BackendController, BackendWorker

API_KEY = os.environ.get("PROXYHUNTER_API_KEY", "")
DATA_DIR = os.environ.get("PROXYHUNTER_DATA_DIR", str(ROOT))
os.environ.setdefault("PROXYHUNTER_HOME", DATA_DIR)

controller = BackendController()
worker = BackendWorker(controller)

app = FastAPI(title="ProxyHunter Backend", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_clients: set[WebSocket] = set()


def require_key(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    return True


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
    return controller.stats()


@app.post("/api/discover")
async def discover(body: dict = {}, _: bool = Depends(require_key)):
    workers = int(body.get("workers", controller.config.get("workers", {}).get("count", 50)))
    controller.config["workers"]["count"] = max(1, min(500, workers))
    worker.submit(controller.discover(workers=workers))
    return {"started": True, "workers": workers}


@app.post("/api/check")
async def check(body: dict = {}, _: bool = Depends(require_key)):
    limit = int(body.get("limit", 0) or 0)
    worker.submit(controller.check(limit=limit))
    return {"started": True}


@app.post("/api/refresh")
async def refresh(body: dict = {}, _: bool = Depends(require_key)):
    limit = int(body.get("limit", 200) or 200)
    worker.submit(controller.discover_and_check(limit=limit))
    return {"started": True}


@app.post("/api/stop")
async def stop(_: bool = Depends(require_key)):
    controller.request_stop()
    return {"ok": True}


@app.get("/api/proxies")
async def proxies(country: str = "", protocol: str = "", max_latency: float = 0, _: bool = Depends(require_key)):
    return {"proxies": controller.proxies(country=country, protocol=protocol, max_latency=max_latency)}


@app.get("/api/sources")
async def sources(_: bool = Depends(require_key)):
    return {"sources": controller.sources()}


@app.post("/api/source_set")
async def source_set(body: dict, _: bool = Depends(require_key)):
    return {"ok": controller.set_source(str(body.get("name", "")), bool(body.get("enabled", True)))}


@app.post("/api/source_test")
async def source_test(body: dict, _: bool = Depends(require_key)):
    return await controller.test_source(str(body.get("name", "")))


@app.post("/api/export")
async def export(body: dict, _: bool = Depends(require_key)):
    directory = body.get("directory", "/tmp/proxyhunter_exports")
    fmt = body.get("format", "json")
    formats = [fmt]
    files = controller.export(directory, body.get("name", "working_proxies"), formats=formats)
    return {"files": files}


@app.get("/api/download/{name}")
async def download(name: str, _: bool = Depends(require_key)):
    path = Path(DATA_DIR) / "exports" / name
    # search common dirs
    for base in (Path(DATA_DIR), Path("/tmp/proxyhunter_exports")):
        candidate = base / name
        if candidate.is_file():
            return FileResponse(str(candidate), filename=name)
    raise HTTPException(status_code=404, detail="file not found")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    if API_KEY:
        # expect first message with api key
        try:
            msg = await asyncio.wait_for(ws.receive_text(), timeout=10)
            if msg != API_KEY:
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
PY