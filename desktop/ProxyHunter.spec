# PyInstaller spec for the Windows portable edition (v3.0).
# Build with: pyinstaller --noconfirm ProxyHunter.spec

import os
from pathlib import Path

# PyInstaller executes spec files without __file__; SPEC is provided instead.
HERE = os.path.dirname(os.path.abspath(SPEC)) if "SPEC" in globals() else os.getcwd()
ROOT = Path(os.path.abspath(os.path.join(HERE, "..")))

a = Analysis(
    [os.path.join(HERE, "app.py")],
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
    icon=os.path.join(HERE, "ProxyHunter.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="ProxyHunter_portable",
)
