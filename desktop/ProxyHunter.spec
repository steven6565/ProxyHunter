# PyInstaller spec for the Windows portable edition (v3.0).
# Build with: pyinstaller --noconfirm ProxyHunter.spec

import os
from pathlib import Path

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

a = Analysis(
    [os.path.join(os.path.dirname(__file__), "app.py")],
    pathex=[str(ROOT), str(ROOT / "backend"), str(ROOT / "shared")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "aiohttp", "aiohttp_socks", "python_socks", "bs4", "geoip2",
        "backend.controller", "shared.exports", "proxyhunter.gateway",
        "proxyhunter.security", "proxyhunter.storage",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "matplotlib", "numpy", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ProxyHunter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(os.path.dirname(__file__), "ProxyHunter.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="ProxyHunter_portable",
)
