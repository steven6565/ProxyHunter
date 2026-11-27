"""Local JSON bridge: Android UI -> embedded Python backend.

v3.1 fix: backend imports are lazy so a missing dependency can never prevent
the HTTP server from starting. All actions return JSON errors instead of
crashing the app, and discovery runs asynchronously (the UI polls real stats).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # android/python -> project root
for entry in (ROOT, ROOT / "shared", ROOT / "backend"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# Chaquopy/Android does not expose the system CA store to OpenSSL.  Point it at
# the certifi bundle that is installed with the app before any SSL context is
# created; otherwise every HTTPS source fetch fails and discovery returns zero.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:  # noqa: BLE001 - fall back to the platform trust store
    pass

CONTROLLER = None
WORKER = None
SERVER: ThreadingHTTPServer | None = None
STARTUP_ERROR = ""
GATEWAY_WARNING = ""
TASKS: set = set()
_LAST_NETWORK_CHECK = 0.0
_NETWORK_OK = False


def _android() -> bool:
    return os.path.exists("/system/build.prop") or bool(os.environ.get("ANDROID_ROOT"))


MAX_SAFE_WORKERS = 200 if _android() else 500


def _internet_ok() -> bool:
    global _LAST_NETWORK_CHECK, _NETWORK_OK
    now = time.monotonic()
    if now - _LAST_NETWORK_CHECK < 30:
        return _NETWORK_OK
    _LAST_NETWORK_CHECK = now
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
            _NETWORK_OK = True
    except OSError:
        _NETWORK_OK = False
    return _NETWORK_OK


def ensure_backend():
    """Initialise the controller once, recording any error instead of raising."""
    global CONTROLLER, WORKER, STARTUP_ERROR, GATEWAY_WARNING
    if CONTROLLER is not None and WORKER is not None:
        return CONTROLLER, WORKER
    if STARTUP_ERROR:
        raise RuntimeError(STARTUP_ERROR)
    try:
        from backend.controller import BackendController, BackendWorker  # lazy

        CONTROLLER = BackendController()
        WORKER = BackendWorker(CONTROLLER)
        try:
            if CONTROLLER.config.get("gateway", {}).get("auto_start", True):
                WORKER.submit(CONTROLLER.gateway_start()).result(timeout=20)
        except Exception as exc:  # noqa: BLE001
            # Gateway failure is not fatal: discovery/validation/export must
            # still work.  Surface it separately instead of blocking the bridge.
            GATEWAY_WARNING = f"gateway start: {type(exc).__name__}: {exc}"
        else:
            for target in (
                Path("/sdcard/Download/ProxyHunter/backend_error.txt"),
                Path(os.environ.get("PROXYHUNTER_HOME", "")) / "backend_error.txt",
            ):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
        return CONTROLLER, WORKER
    except Exception as exc:  # noqa: BLE001
        STARTUP_ERROR = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
        for target in (
            Path("/sdcard/Download/ProxyHunter/backend_error.txt"),
            Path(os.environ.get("PROXYHUNTER_HOME", "")) / "backend_error.txt",
        ):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(STARTUP_ERROR)
            except OSError:
                pass
        raise RuntimeError(STARTUP_ERROR) from exc

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
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
            self._send({
                "ok": CONTROLLER is not None and not STARTUP_ERROR,
                "ready": CONTROLLER is not None and not STARTUP_ERROR,
                "version": "3.1.2",
                "backend": "READY" if CONTROLLER is not None and not STARTUP_ERROR else "ERROR",
                "gateway": "ONLINE" if CONTROLLER and CONTROLLER.gateway.running else "OFFLINE",
                "internet": "ONLINE" if _internet_ok() else "OFFLINE",
                "error": STARTUP_ERROR,
                "gateway_warning": GATEWAY_WARNING,
            })
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
        except (json.JSONDecodeError, ValueError):
            params = {}
        try:
            controller, worker = ensure_backend()
        except Exception as exc:  # noqa: BLE001
            self._send({"error": f"backend unavailable: {exc}"}, 503)
            return

        def background(coro) -> None:
            future = worker.submit(coro)
            TASKS.add(future)
            future.add_done_callback(TASKS.discard)

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
            elif action == "sources":
                result = {"sources": controller.sources()}
            elif action == "source_set":
                result = {"ok": controller.set_source(
                    str(params.get("name", "")), bool(params.get("enabled", True))
                )}
            elif action == "source_toggle":
                result = {"ok": controller.toggle_source(
                    str(params.get("name", "")), bool(params.get("enabled", True))
                )}
            elif action == "source_diagnostics":
                result = {"sources": worker.submit(controller.source_diagnostics()).result(timeout=120)}
            elif action == "source_test":
                result = worker.submit(controller.test_source(str(params.get("name", "")))).result(timeout=30)
            elif action == "discover":
                workers = max(1, min(MAX_SAFE_WORKERS, int(params.get("workers", 50) or 50)))
                controller.config["workers"]["count"] = workers
                background(controller.discover(workers=workers))
                result = {"started": True, "workers": workers}
            elif action == "check":
                limit = int(params.get("limit", 0) or 0)
                background(controller.check(limit=limit))
                result = {"started": True}
            elif action == "refresh":
                limit = int(params.get("limit", 200) or 200)
                background(controller.discover_and_check(limit=limit))
                result = {"started": True}
            elif action == "stop":
                controller.request_stop()
                result = {"ok": True}
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
    def start(port: int = 8765, data_dir: str = "") -> None:
        global SERVER
        if SERVER is not None:
            return
        if data_dir:
            os.environ["PROXYHUNTER_HOME"] = str(data_dir)
        try:
            ensure_backend()
        except Exception:
            pass  # /health will report the error; never kill the service
        try:
            SERVER = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
        except OSError:
            # A previous service instance may still own the port. If it is a
            # healthy ProxyHunter bridge, simply reuse it instead of crashing.
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    if json.load(response).get("ok"):
                        return
            except Exception:  # noqa: BLE001
                pass
            raise
        SERVER.serve_forever()

    @staticmethod
    def stop() -> None:
        global SERVER
        if SERVER is not None:
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
            SERVER = None
