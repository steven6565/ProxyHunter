#!/usr/bin/env python3
"""Build the standalone onefile Windows EXE with PyInstaller.

Uses exactly: --onefile --windowed --clean. No system Python is required at
runtime; python311.dll, Tcl/Tk and all dependencies are embedded.
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.__main__ import run

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

HIDDEN = [
    "backend", "backend.controller", "shared", "shared.exports",
    "proxyhunter.checker", "proxyhunter.config", "proxyhunter.dashboard",
    "proxyhunter.discovery", "proxyhunter.gateway", "proxyhunter.geo",
    "proxyhunter.logging_utils", "proxyhunter.models", "proxyhunter.resources",
    "proxyhunter.security", "proxyhunter.storage", "proxyhunter.utils",
    "aiohttp", "aiohttp_socks", "python_socks", "bs4",
    "rich", "rich.console", "rich.live", "rich.panel", "rich.table",
    "rich.progress", "rich.prompt", "rich.text",
    "geoip2", "maxminddb", "tkinter", "_tkinter", "tkinter.ttk",
    "tkinter.filedialog", "tkinter.messagebox", "pystray",
    "PIL", "PIL.Image", "PIL.ImageDraw", "sqlite3", "ssl", "asyncio",
]

args = [
    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--name", "ProxyHunter",
    "--icon", str(HERE / "ProxyHunter.ico"),
    "--distpath", str(ROOT / "builds"),
    "--paths", str(ROOT),
    "--paths", str(ROOT / "backend"),
    "--paths", str(ROOT / "shared"),
]
for module in HIDDEN:
    args += ["--hidden-import", module]
args.append(str(HERE / "app.py"))

if __name__ == "__main__":
    run(args)
