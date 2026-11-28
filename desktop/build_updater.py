#!/usr/bin/env python3
"""Build the separate updater helper EXE used by the automatic update system."""

from __future__ import annotations
from pathlib import Path
from PyInstaller.__main__ import run

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
args = [
    "--onefile", "--windowed", "--clean", "--noconfirm",
    "--name", "ProxyHunterUpdater",
    "--distpath", str(ROOT / "builds"),
    "--paths", str(ROOT),
    str(HERE / "updater.py"),
]
run(args)