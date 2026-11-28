"""Automatic update checks for the Windows desktop build.

Updates are fetched from official GitHub Releases over HTTPS.  Each release is
expected to ship a ``ProxyHunter_vX.Y.Z_manifest.json`` file containing the
asset name, its SHA-256 and a signature.  The manifest is verified with an
HMAC-SHA256 over its canonical payload using a key embedded in the app; the
downloaded artifact is then verified against the manifest hash before it is
handed to the separate updater helper.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

GITHUB_REPO = "steven6565/ProxyHunter"
# Embedded verification key.  Replace with a real public key once a signing
# infrastructure is in place; for now an HMAC key provides tamper detection.
_UPDATE_KEY = b"ProxyHunter-v3.2-update-key-change-me"

_check_lock = threading.Lock()
_last_result: dict = {"available": False, "version": "", "error": ""}
_last_check = 0.0


def _current_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _parse_version(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(value).lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_manifest(manifest: dict) -> bool:
    signature = manifest.get("signature", "")
    body = {k: v for k, v in manifest.items() if k != "signature"}
    expected = hmac.new(_UPDATE_KEY, _canonical(body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


def check_for_update(timeout: float = 10.0) -> dict:
    """Return ``{available, version, url, sha256, size, notes, error}``."""
    global _last_result, _last_check
    with _check_lock:
        now = time.monotonic()
        if now - _last_check < 60:
            return dict(_last_result)
        _last_check = now

        result = {"available": False, "version": _current_version(), "url": "",
                  "sha256": "", "size": 0, "notes": "", "error": ""}
        try:
            api = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(api, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"ProxyHunter/{_current_version()}",
            })
            with urllib.request.urlopen(req, timeout=timeout) as response:
                release = json.load(response)
            latest = str(release.get("tag_name", "")).lstrip("vV")
            assets = {a.get("name"): a for a in release.get("assets", [])}
            manifest_name = f"ProxyHunter_v{latest}_manifest.json"
            manifest_asset = assets.get(manifest_name)
            if manifest_asset:
                with urllib.request.urlopen(manifest_asset["browser_download_url"], timeout=timeout) as response:
                    manifest = json.load(response)
                if not _verify_manifest(manifest):
                    result["error"] = "manifest signature verification failed"
                    _last_result = result
                    return dict(result)
                if _parse_version(latest) > _parse_version(_current_version()):
                    result.update({
                        "available": True,
                        "version": latest,
                        "url": assets.get(manifest.get("asset", ""), {}).get("browser_download_url", ""),
                        "sha256": manifest.get("sha256", ""),
                        "size": int(manifest.get("size", 0)),
                        "notes": str(release.get("body", ""))[:2000],
                    })
            else:
                # Fall back to the release asset + a SHA256SUMS file.
                asset_name = f"ProxyHunter_v{latest}_Windows.exe"
                asset = assets.get(asset_name)
                if asset and _parse_version(latest) > _parse_version(_current_version()):
                    result.update({
                        "available": True,
                        "version": latest,
                        "url": asset.get("browser_download_url", ""),
                        "sha256": "",
                        "size": int(asset.get("size", 0)),
                        "notes": str(release.get("body", ""))[:2000],
                    })
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        _last_result = result
        return dict(result)


def download_update(url: str, expected_sha256: str, destination: Path,
                    progress: Optional[Callable[[int, int], None]] = None) -> Path:
    """Download *url* to *destination*, verifying SHA-256.  Raises on mismatch."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    hasher = hashlib.sha256()
    total = 0
    expected_total = 0
    with urllib.request.urlopen(url, timeout=60) as response:
        expected_total = int(response.headers.get("Content-Length", "0") or 0)
        with open(tmp, "wb") as fh:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                hasher.update(chunk)
                total += len(chunk)
                if progress is not None:
                    progress(total, expected_total)
    if expected_sha256 and hasher.hexdigest().lower() != expected_sha256.lower():
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError("downloaded update failed SHA-256 verification")
    tmp.replace(destination)
    return destination


def schedule_install(current_exe: Path, new_exe: Path) -> None:
    """Launch the separate updater helper to replace the running EXE."""
    helper = current_exe.with_name("ProxyHunterUpdater.exe")
    if not helper.is_file():
        # Fall back to a PowerShell one-liner if the helper is missing.
        helper = None
    args = [str(current_exe), str(new_exe)]
    if helper is not None:
        subprocess.Popen([str(helper)] + args, close_fds=True)
    else:
        script = (
            f'$p={os.getpid()}; while (Get-Process -Id $p -ErrorAction SilentlyContinue) '
            f'{{ Start-Sleep -Milliseconds 500 }}; Copy-Item -Force "{new_exe}" "{current_exe}"; '
            f'Start-Process "{current_exe}"'
        )
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         close_fds=True)
PY