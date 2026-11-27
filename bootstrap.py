"""Dependency bootstrap (stdlib only).

Runs before any third-party import so a fresh checkout can install its own
requirements with a single ``python3 main.py`` command.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys

REQUIREMENTS = [
    ("aiohttp", "aiohttp>=3.9.0"),
    ("aiohttp_socks", "aiohttp-socks>=0.8.0"),
    ("python_socks", "python-socks>=2.5.0"),
    ("bs4", "beautifulsoup4>=4.12.0"),
    ("rich", "rich>=13.7.0"),
    ("geoip2", "geoip2>=4.2.0"),
]


def platform_notes() -> list[str]:
    notes: list[str] = []
    if sys.version_info < (3, 11):
        notes.append("Python 3.11+ is recommended; some async features may be missing.")
    if platform.system() == "Linux" and "android" in platform.platform().lower():
        notes.append("Android/Termux: psutil cannot be built; CPU/RAM falls back to /proc automatically.")
    if importlib.util.find_spec("psutil") is None:
        notes.append("psutil not installed (optional); resource monitor uses /proc where available.")
    if shutil.which("openssl") is None:
        notes.append("openssl not found: TLS gateway listener needs a cert/key (generate one before VPS use).")
    return notes


def ensure_dependencies(verbose: bool = True) -> None:
    if verbose:
        for note in platform_notes():
            print(f"Proxy Hunter note: {note}")
    missing = [package for module, package in REQUIREMENTS if importlib.util.find_spec(module) is None]
    if not missing:
        return
    if verbose:
        print(f"Proxy Hunter: installing {len(missing)} missing dependency(ies): {', '.join(missing)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing])
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SystemExit(
            f"Automatic dependency installation failed ({exc}).\n"
            "Install manually:  python3 -m pip install -r requirements.txt"
        ) from exc
