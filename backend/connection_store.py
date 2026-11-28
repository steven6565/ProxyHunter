"""Persist the Windows client's backend connection.

The API key is protected with Windows DPAPI (per-user encryption) when
available.  A plain-text fallback is kept for non-Windows development and for
Wine/Winlator environments where crypt32 is unavailable, but the file is
created with owner-only permissions on POSIX.

This module deliberately uses only the standard library so the packaged
``--selftest`` path can load it without importing aiohttp/Tkinter.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / "ProxyHunter" / "connection.json"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    """Call CryptProtectData/CryptUnprotectData; return None on any failure."""
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buffer = ctypes.create_string_buffer(data)
        blob_in = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DataBlob()
        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        # Both functions share the same seven-argument signature.
        ok = function(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        )
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            if blob_out.pbData:
                kernel32.LocalFree(blob_out.pbData)
    except Exception:  # noqa: BLE001 - fall back to plain text
        return None


def load_connection() -> dict:
    """Return ``{"url": str, "api_key": str}`` or an empty dict."""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    api_key = str(data.get("api_key") or "")
    encrypted = data.get("api_key_dpapi")
    if encrypted:
        try:
            raw = _dpapi(base64.b64decode(str(encrypted)), protect=False)
            if raw:
                api_key = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            api_key = ""
    return {"url": str(data.get("url") or "").rstrip("/"), "api_key": api_key}


def save_connection(url: str, api_key: str) -> None:
    """Atomically persist the connection, encrypting the key with DPAPI."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {"url": str(url).rstrip("/")}
    if api_key:
        raw = api_key.encode("utf-8")
        protected = _dpapi(raw, protect=True)
        # Only use DPAPI if this process can actually decrypt the value again.
        if protected and _dpapi(protected, protect=False) == raw:
            payload["api_key_dpapi"] = base64.b64encode(protected).decode("ascii")
        else:
            payload["api_key"] = api_key
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG_PATH)
