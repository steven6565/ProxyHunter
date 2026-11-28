"""PyInstaller runtime hook: never leave a windowed EXE stuck on an error dialog.

CI (and users on Wine/Winlator) cannot dismiss a modal traceback dialog.  Write
the traceback to ``crash.log`` next to the working directory and terminate with
a nonzero exit code instead.
"""

from __future__ import annotations

import os
import sys
import time
import traceback


def _write(message: str) -> None:
    try:
        with open("crash.log", "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except OSError:
        pass


def _excepthook(exc_type, exc, tb):
    _write("unhandled exception:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
    os._exit(1)


sys.excepthook = _excepthook
if "--selftest" in sys.argv or os.environ.get("PROXYHUNTER_SELFTEST") == "1":
    _write(f"boot argv={sys.argv!r} frozen={bool(getattr(sys, 'frozen', False))}")
