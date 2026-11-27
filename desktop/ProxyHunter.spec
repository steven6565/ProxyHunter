# PyInstaller spec for ProxyHunter v3.1.1 — standalone onefile Windows EXE.
# Equivalent to: pyinstaller --onefile --windowed --clean --noconfirm

import os

# PyInstaller executes spec files without __file__; SPEC is provided instead.
HERE = os.path.dirname(os.path.abspath(SPEC)) if "SPEC" in globals() else os.getcwd()
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ICON = os.path.join(HERE, "ProxyHunter.ico")

a = Analysis(
    [os.path.join(HERE, "app.py")],
    pathex=[ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "shared")],
    binaries=[],
    datas=[(ICON, "assets")],
    hiddenimports=[
        # Backend + shared engine
        "backend", "backend.controller", "shared", "shared.exports",
        "proxyhunter", "proxyhunter.checker", "proxyhunter.config",
        "proxyhunter.dashboard", "proxyhunter.discovery", "proxyhunter.gateway",
        "proxyhunter.geo", "proxyhunter.logging_utils",
        "proxyhunter.models", "proxyhunter.resources", "proxyhunter.security",
        "proxyhunter.storage", "proxyhunter.utils",
        # Networking / parsing / UI runtime (all bundled, no system Python needed)
        "aiohttp", "aiohttp_socks", "python_socks", "bs4",
        "rich", "rich.console", "rich.live", "rich.panel", "rich.table",
        "rich.progress", "rich.prompt", "rich.text",
        "geoip2", "maxminddb",
        "tkinter", "_tkinter", "tkinter.ttk", "tkinter.filedialog",
        "tkinter.messagebox", "pystray", "PIL", "PIL.Image", "PIL.ImageDraw",
        "sqlite3", "ssl", "asyncio",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "matplotlib", "numpy", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

# Onefile: python311.dll, Tcl/Tk runtime and all imports are embedded in the
# executable and extracted to a private temp dir at launch.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ProxyHunter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)
