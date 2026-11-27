"""Local JSON bridge: Android UI -> embedded Python backend.

Runs a tiny loopback-only HTTP server on port 8765. No token is sent to any
remote service; the socket is bound to 127.0.0.1 and never exposed.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]  # android/app/src/main/python -> project root
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "backend"))

from backend.controller import BackendController, BackendWorker  # noqa: E402

CONTROLLER: BackendController | None = None
WORKER: BackendWorker | None = None
SERVER: ThreadingHTTPServer | None = None


def ensure_backend() -> tuple[BackendController, BackendWorker]:
    global CONTROLLER, WORKER
    if CONTROLLER is None:
        CONTROLLER = BackendController()
    if WORKER is None:
        WORKER = BackendWorker(CONTROLLER)
    return CONTROLLER, WORKER


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep logcat quiet
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send({"ok": True, "version": "3.0.0"})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self.path.startswith("/api/"):
            self._send({"error": "not found"}, 404)
            return
        action = self.path[5:]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            params = {}
        controller, worker = ensure_backend()
        try:
            if action == "stats":
                result = controller.stats()
            elif action == "proxies":
                result = {"proxies": controller.proxies(
                    country=params.get("country", ""), protocol=params.get("protocol", ""),
                    max_latency=float(params.get("max_latency", 0) or 0),
                )}
            elif action == "countries":
                result = {"countries": controller.countries(), "capacity": controller.capacity()}
            elif action == "discover":
                result = {"proxies": len(worker.submit(controller.discover()).result(timeout=600))}
            elif action == "check":
                result = {"checked": len(worker.submit(controller.check(limit=int(params.get("limit", 0)))).result(timeout=900))}
            elif action == "stop":
                controller.request_stop()
                result = {"ok": True}
            elif action == "refresh":
                result = worker.submit(controller.discover_and_check(limit=int(params.get("limit", 200)))).result(timeout=900)
            elif action == "gateway_start":
                result = {"ok": worker.submit(controller.gateway_start()).result(timeout=30)}
            elif action == "gateway_stop":
                worker.submit(controller.gateway_stop()).result(timeout=30)
                result = {"ok": True}
            elif action == "gateway_countries":
                ok, warning = controller.gateway_select_countries(params.get("countries", "all"))
                result = {"ok": ok, "warning": warning}
            elif action == "gateway_mode":
                result = {"ok": controller.gateway_set_mode(params.get("mode", "per_connection"))}
            elif action == "exports":
                from shared.exports import export_history
                result = {"files": export_history(params.get("directory", "/sdcard/Download/ProxyHunter"))}
            elif action == "export":
                from shared.exports import suggested_name
                files = controller.export(
                    params.get("directory", "/sdcard/Download/ProxyHunter"),
                    suggested_name(params.get("kind", "all"), params.get("value", "")),
                    params.get("formats", ["txt"]), params.get("address_format", "ip_port"),
                )
                result = {"files": files}
            elif action == "gateway_auth":
                controller.gateway_set_credentials(str(params.get("username", "")), str(params.get("password", "")))
                result = {"ok": True}
            else:
                self._send({"error": "unknown action"}, 404)
                return
            self._send(result)
        except Exception as exc:  # noqa: BLE001
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)


class BridgeServer:
    """Entry point called from Kotlin via Chaquopy."""

    @staticmethod
    def start(port: int = 8765) -> None:
        global SERVER
        ensure_backend()
        if SERVER is not None:
            return
        SERVER = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
        SERVER.serve_forever()

    @staticmethod
    def stop() -> None:
        global SERVER
        if SERVER is not None:
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
            SERVER = None
