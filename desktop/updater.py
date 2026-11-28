#!/usr/bin/env python3
"""Separate updater helper for the Windows onefile EXE.

Usage: ProxyHunterUpdater.exe <current_exe> <new_exe> [pid]

Waits for the main application process to exit, backs up the running EXE,
replaces it with the downloaded update, launches it and verifies it starts.
On failure the backup is restored (rollback).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: ProxyHunterUpdater <current_exe> <new_exe> [pid]")
        return 2
    current = Path(sys.argv[1])
    new = Path(sys.argv[2])
    pid = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None

    # Wait for the main process to exit.
    if pid is not None:
        deadline = time.monotonic() + 120
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.5)

    backup = current.with_suffix(current.suffix + ".bak")
    try:
        if current.is_file():
            shutil.copy2(current, backup)
        shutil.copy2(new, current)
    except OSError as exc:
        print(f"copy failed: {exc}")
        if backup.is_file():
            try:
                shutil.copy2(backup, current)
            except OSError:
                pass
        return 1

    # Launch the updated application and verify it stays alive briefly.
    try:
        proc = subprocess.Popen([str(current)], close_fds=True)
    except OSError as exc:
        print(f"launch failed: {exc}")
        if backup.is_file():
            shutil.copy2(backup, current)
        return 1

    time.sleep(8)
    if proc.poll() is not None:
        # Failed to stay running -> rollback.
        try:
            if backup.is_file():
                shutil.copy2(backup, current)
        except OSError:
            pass
        return 1

    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())