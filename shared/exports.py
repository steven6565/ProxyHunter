"""Shared export engine used by the CLI, Android app and Windows desktop app."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from proxyhunter.models import Proxy, utc_now

HISTORY_FILE = "export_history.json"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    os.replace(tmp, path)


def _lines(proxies: list[Proxy], fmt: str) -> str:
    return "\n".join(p.export_line(fmt) for p in proxies) + ("\n" if proxies else "")


def export_proxies(
    proxies: Iterable[Proxy],
    directory: str | Path,
    name: str = "working_proxies",
    formats: Iterable[str] = ("txt", "csv", "json"),
    address_format: str = "ip_port",
    history: bool = True,
) -> list[dict]:
    """Write proxy exports and return file metadata entries."""
    items = list(proxies)
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    created: list[dict] = []
    stamp = utc_now()

    if "txt" in formats:
        path = root / f"{name}.txt"
        _atomic_write(path, _lines(items, address_format))
        created.append(_metadata(path, len(items), stamp, "txt"))
    if "csv" in formats:
        path = root / f"{name}.csv"
        tmp = path.with_name(path.name + ".tmp")
        fields = [
            "host", "port", "protocol", "country", "country_code", "city", "isp",
            "response_time_ms", "last_checked", "exit_ip", "address", "url",
        ]
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for p in items:
                row = p.to_dict()
                writer.writerow({key: row.get(key, "") for key in fields})
        os.replace(tmp, path)
        created.append(_metadata(path, len(items), stamp, "csv"))
    if "json" in formats:
        path = root / f"{name}.json"
        payload = {"generated_at": stamp, "total": len(items), "proxies": [p.to_dict() for p in items]}
        _atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        created.append(_metadata(path, len(items), stamp, "json"))

    if history and created:
        add_history(root, created)
    return created


def _metadata(path: Path, count: int, stamp: str, fmt: str) -> dict:
    return {
        "name": path.name,
        "path": str(path),
        "format": fmt,
        "count": count,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "timestamp": stamp,
    }


def add_history(root: str | Path, entries: list[dict]) -> None:
    root = Path(root)
    path = root / HISTORY_FILE
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
        existing = []
    existing.extend(entries)
    _atomic_write(path, json.dumps(existing[-200:], indent=2) + "\n")


def export_history(root: str | Path, limit: int = 50) -> list[dict]:
    path = Path(root) / HISTORY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(reversed(data[-limit:]))
    except (OSError, json.JSONDecodeError):
        return []


def delete_export(entry: dict) -> bool:
    try:
        path = Path(entry["path"])
        if path.exists():
            path.unlink()
        return True
    except (OSError, KeyError):
        return False


def suggested_name(kind: str, value: str = "") -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)[:24]
    if kind == "all":
        return "working_proxies"
    if kind == "country":
        return f"working_proxies_{safe.upper()}" if safe else "working_proxies_country"
    if kind == "protocol":
        return f"working_{safe.lower()}"
    if kind == "recent":
        return "working_recently_validated"
    if kind == "selected":
        return "working_selected"
    return f"working_{safe or 'filtered'}"


def default_export_dir(desktop: bool = False) -> Path:
    if desktop:
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads" / "ProxyHunter"
    return Path("/sdcard/Download/ProxyHunter")
