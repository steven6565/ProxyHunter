"""Non-interactive smoke test for the packaged Windows client (v4.0.0).

This module is imported by ``desktop/app.py`` *before* Tkinter, the GUI or the
remote-controller stack is loaded.  It must therefore use only the standard
library (plus ``backend.connection_store``) and must always terminate.

Every step is bounded.  A daemon watchdog writes a failure marker and calls
``os._exit`` if the main thread ever blocks, so the Windows CI job can never
hang on a modal dialog, a stuck socket or a non-daemon thread.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "4.0.0"
SECTIONS = ["Dashboard", "Proxy List", "Rotating Gateway", "Downloads", "Settings", "About"]
RESULT_FILE = Path("selftest.json")
LOG_FILE = Path("selftest.log")
WATCHDOG_SECONDS = 150

_finished = threading.Event()
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def _write_result(payload: dict) -> None:
    _finished.set()
    try:
        tmp = RESULT_FILE.with_name(RESULT_FILE.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, RESULT_FILE)
    except OSError as exc:
        _log(f"could not write {RESULT_FILE}: {exc}")
    _log("RESULT " + json.dumps(payload, sort_keys=True))


def _watchdog() -> None:
    if _finished.wait(WATCHDOG_SECONDS):
        return
    _write_result({
        "ok": False,
        "version": VERSION,
        "error": f"selftest watchdog timeout after {WATCHDOG_SECONDS}s",
        "argv": sys.argv,
        "frozen": bool(getattr(sys, "frozen", False)),
    })
    os._exit(3)


def _call(base: str, key: str, path: str, method: str = "GET",
          body: dict | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-API-Key": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base.rstrip("/") + path, data=data,
                                     headers=headers, method=method)
    with _opener.open(request, timeout=timeout) as response:
        raw = response.read()
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", "replace")[:500]}
        return int(response.status), payload


def _download(base: str, key: str, name: str, destination: Path, timeout: float = 30.0) -> int:
    safe = Path(str(name)).name
    url = base.rstrip("/") + "/api/download/" + urllib.parse.quote(safe)
    request = urllib.request.Request(url, headers={"X-API-Key": key})
    with _opener.open(request, timeout=timeout) as response:
        data = response.read()
    destination.write_bytes(data)
    return len(data)


def _wait_for_discovery(base: str, key: str, deadline: float) -> tuple[int, int, dict]:
    discovered = 0
    checked = 0
    last: dict = {}
    while time.monotonic() < deadline:
        remaining = max(1.0, min(8.0, deadline - time.monotonic()))
        try:
            _, last = _call(base, key, "/api/stats", timeout=remaining)
            discovered = max(discovered, int(last.get("discovered", 0) or 0))
            checked = max(checked, int(last.get("checked", 0) or 0))
            # Wait for the operation to finish so last_discovered is populated
            # even when no proxy has been validated into SQLite yet.
            if discovered > 0 and str(last.get("operation", "")).lower() == "idle":
                break
        except Exception as exc:  # noqa: BLE001
            last = {"stats_error": f"{type(exc).__name__}: {exc}"}
        time.sleep(2)
    return discovered, checked, last


def run_selftest() -> int:
    started = time.monotonic()
    LOG_FILE.write_text("", encoding="utf-8")
    _log(
        "start version=%s frozen=%s argv=%r cwd=%s meipass=%s"
        % (VERSION, bool(getattr(sys, "frozen", False)), sys.argv, Path.cwd(),
           getattr(sys, "_MEIPASS", ""))
    )
    threading.Thread(target=_watchdog, name="selftest-watchdog", daemon=True).start()

    base = os.environ.get("PROXYHUNTER_BACKEND_URL", "").strip().rstrip("/")
    key = os.environ.get("PROXYHUNTER_API_KEY", "").strip()
    payload: dict = {
        "ok": False,
        "version": VERSION,
        "sections": SECTIONS,
        "argv": sys.argv,
        "frozen": bool(getattr(sys, "frozen", False)),
        "backend_url_set": bool(base),
        "sources_total": 0,
        "sources_enabled": 0,
        "discovered": 0,
        "checked": 0,
        "export_files": [],
        "json_verified": False,
        "csv_verified": False,
        "txt_verified": False,
        "gateway_ok": False,
        "auth_ok": False,
        "connection_saved": False,
        "resources_ok": False,
    }

    if not base:
        payload["error"] = "PROXYHUNTER_BACKEND_URL is not set"
        _write_result(payload)
        return 1

    # Persist and reload the connection (DPAPI on Windows, owner-only fallback).
    try:
        from backend.connection_store import load_connection, save_connection

        save_connection(base, key)
        stored = load_connection()
        payload["connection_saved"] = (
            stored.get("url") == base and (not key or stored.get("api_key") == key)
        )
        _log(f"connection saved={payload['connection_saved']} url={base}")
    except Exception as exc:  # noqa: BLE001
        payload["connection_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["connection_error"])

    # Health.
    try:
        status, health = _call(base, key, "/health", timeout=10)
        payload["backend"] = health
        payload["health_status"] = status
        _log(f"health status={status} body={health}")
    except Exception as exc:  # noqa: BLE001
        payload["backend"] = {"error": f"{type(exc).__name__}: {exc}"}
        _log(f"health failed: {payload['backend']}")

    # Authentication must reject a wrong key when a key is configured.
    if key:
        try:
            _call(base, "definitely-wrong-key", "/api/stats", timeout=10)
            payload["auth_ok"] = False
            payload["auth_error"] = "wrong API key was accepted"
        except urllib.error.HTTPError as exc:
            payload["auth_ok"] = exc.code == 401
        except Exception as exc:  # noqa: BLE001
            payload["auth_ok"] = False
            payload["auth_error"] = f"{type(exc).__name__}: {exc}"
    else:
        payload["auth_ok"] = True
        payload["auth_note"] = "no API key configured; auth check skipped"
    _log(f"auth_ok={payload['auth_ok']}")

    # Source configuration.
    try:
        status, source_data = _call(base, key, "/api/sources", timeout=15)
        sources = source_data.get("sources", [])
        payload["sources_total"] = len(sources)
        payload["sources_enabled"] = sum(1 for item in sources if item.get("enabled", True))
        payload["sources_status"] = status
        _log(f"sources total={len(sources)} enabled={payload['sources_enabled']}")
    except Exception as exc:  # noqa: BLE001
        payload["sources_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["sources_error"])

    # Discovery.
    try:
        status, started_body = _call(base, key, "/api/discover", method="POST",
                                     body={"workers": 50}, timeout=15)
        payload["discover_status"] = status
        payload["discover_response"] = started_body
        _log(f"discover status={status} body={started_body}")
    except Exception as exc:  # noqa: BLE001
        payload["discover_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["discover_error"])

    discovered, checked, stats = _wait_for_discovery(base, key, time.monotonic() + 60)
    payload["discovered"] = discovered
    payload["checked"] = checked
    payload["stats"] = stats
    _log(f"discovery discovered={discovered} checked={checked}")

    # Start validation in the background so the export contains checked rows
    # when the server has enough time, without making the smoke test flaky.
    try:
        _call(base, key, "/api/check", method="POST", body={"limit": 25}, timeout=15)
    except Exception as exc:  # noqa: BLE001
        payload["check_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["check_error"])

    # Export all discovered proxies to three formats, then download each file.
    export_dir = Path.cwd() / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []
    try:
        status, export_data = _call(
            base, key, "/api/export", method="POST",
            body={
                "name": "selftest_proxies",
                "formats": ["txt", "csv", "json"],
                "working_only": False,
                "address_format": "ip_port",
            },
            timeout=60,
        )
        payload["export_status"] = status
        files = export_data.get("files", [])
        payload["export_response_count"] = len(files)
        for item in files:
            name = Path(str(item.get("name", ""))).name
            if not name:
                continue
            destination = export_dir / name
            size = _download(base, key, name, destination, timeout=30)
            entry = dict(item)
            entry["local_path"] = str(destination)
            entry["local_size"] = size
            downloaded.append(entry)
            _log(f"downloaded {name} bytes={size}")
    except Exception as exc:  # noqa: BLE001
        payload["export_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["export_error"])

    payload["export_files"] = [item.get("name") for item in downloaded]
    json_file = next((item for item in downloaded if str(item.get("name", "")).endswith(".json")), None)
    csv_file = next((item for item in downloaded if str(item.get("name", "")).endswith(".csv")), None)
    txt_file = next((item for item in downloaded if str(item.get("name", "")).endswith(".txt")), None)
    if json_file:
        try:
            data = json.loads(Path(json_file["local_path"]).read_text(encoding="utf-8"))
            proxies = data.get("proxies", [])
            payload["export_total"] = int(data.get("total", 0) or 0)
            payload["json_verified"] = (
                isinstance(proxies, list)
                and int(data.get("total", -1)) == len(proxies)
                and len(proxies) > 0
            )
        except Exception as exc:  # noqa: BLE001
            payload["json_error"] = f"{type(exc).__name__}: {exc}"
    if csv_file:
        try:
            lines = Path(csv_file["local_path"]).read_text(encoding="utf-8").splitlines()
            payload["csv_verified"] = bool(lines) and "host" in lines[0] and "port" in lines[0] and len(lines) >= 2
        except Exception as exc:  # noqa: BLE001
            payload["csv_error"] = f"{type(exc).__name__}: {exc}"
    if txt_file:
        try:
            payload["txt_verified"] = Path(txt_file["local_path"]).stat().st_size > 0
        except OSError:
            payload["txt_verified"] = False
    _log(
        f"export files={payload['export_files']} json={payload['json_verified']} "
        f"csv={payload['csv_verified']} txt={payload['txt_verified']}"
    )

    # Gateway control and status.
    try:
        status, gateway_body = _call(base, key, "/api/gateway_start", method="POST",
                                     body={}, timeout=20)
        payload["gateway_start_status"] = status
        payload["gateway_start_response"] = gateway_body
        time.sleep(1)
        _, latest = _call(base, key, "/api/stats", timeout=10)
        payload["gateway"] = latest.get("gateway")
        payload["gateway_ok"] = bool(
            gateway_body.get("ok", gateway_body.get("running", False))
            and latest.get("gateway") == "ONLINE"
        )
        _log(f"gateway start={gateway_body} stats={payload['gateway']}")
    except Exception as exc:  # noqa: BLE001
        payload["gateway_error"] = f"{type(exc).__name__}: {exc}"
        _log(payload["gateway_error"])

    # Packaged resources must be present inside the onefile bundle.
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    payload["resources_ok"] = (resource_root / "sources.json").is_file() and (
        resource_root / "config.json"
    ).is_file()
    payload["resource_root"] = str(resource_root)
    _log(f"resources_ok={payload['resources_ok']} root={resource_root}")

    # Optional server-side control endpoints (record, do not fail the build).
    for path, field in (("/api/countries", "countries"), ("/api/capacity", "capacity"),
                        ("/api/rotation_modes", "rotation_modes")):
        try:
            _, data = _call(base, key, path, timeout=10)
            payload[field] = data
        except Exception as exc:  # noqa: BLE001
            payload[f"{field}_error"] = f"{type(exc).__name__}: {exc}"

    payload["duration_seconds"] = round(time.monotonic() - started, 2)
    payload["ok"] = bool(
        payload.get("backend", {}).get("ok")
        and payload.get("auth_ok")
        and payload.get("connection_saved")
        and payload.get("sources_total", 0) > 0
        and payload.get("sources_enabled", 0) > 0
        and payload.get("discovered", 0) > 0
        and len(payload.get("export_files", [])) == 3
        and payload.get("json_verified")
        and payload.get("csv_verified")
        and payload.get("txt_verified")
        and payload.get("gateway_ok")
        and payload.get("resources_ok")
    )
    _write_result(payload)
    _log(f"done ok={payload['ok']} duration={payload['duration_seconds']}s")
    return 0 if payload["ok"] else 1
