#!/usr/bin/env python3
"""Separate updater helper for the Windows onefile EXE.

Usage: ProxyHunterUpdater.exe <current_exe> <new_exe> [pid] [expected_version]

Waits for the main application process to exit, backs up the running EXE,
replaces it with the downloaded update, verifies the replacement reports the
expected version, launches it and checks that it stays alive.  On any failure
the backup is restored (rollback).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _alive(pid: int) -> bool:
    # os.kill(pid, 0) is not reliable on Windows/Wine (WinError 6 / SystemError).
    # Prefer a ctypes OpenProcess check, and otherwise assume the process is gone.
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _reported_version(exe: Path) -> str:
    """Run ``exe --version`` and return the version it writes, or an empty string."""
    handle, path = tempfile.mkstemp(prefix="proxyhunter-version-", suffix=".txt")
    os.close(handle)
    version_file = Path(path)
    env = dict(os.environ)
    env["PROXYHUNTER_VERSION_FILE"] = str(version_file)
    try:
        completed = subprocess.run(
            [str(exe), "--version"], env=env, timeout=25,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if completed.returncode != 0:
            return ""
        return version_file.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            version_file.unlink(missing_ok=True)
        except OSError:
            pass


def _rollback(current: Path, backup: Path) -> int:
    try:
        if backup.is_file():
            shutil.copy2(backup, current)
    except OSError:
        pass
    return 1


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: ProxyHunterUpdater <current_exe> <new_exe> [pid] [expected_version]")
        return 2
    current = Path(sys.argv[1])
    new = Path(sys.argv[2])
    pid = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None
    expected_version = sys.argv[4].strip() if len(sys.argv) > 4 else ""

    # Give the main process time to release its file handles (Wine-safe).
    time.sleep(2)
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
        return _rollback(current, backup)

    # Verify the new binary before launching the full GUI.  This catches a
    # truncated/corrupt download even when the file size and hash were valid.
    if expected_version:
        reported = _reported_version(current)
        if reported != expected_version:
            print(f"version verification failed: expected {expected_version!r}, got {reported!r}")
            return _rollback(current, backup)

    # Launch the updated application and verify it stays alive briefly.
    try:
        proc = subprocess.Popen([str(current)], close_fds=True)
    except OSError as exc:
        print(f"launch failed: {exc}")
        return _rollback(current, backup)

    time.sleep(8)
    if proc.poll() is not None:
        # Failed to stay running -> rollback.
        return _rollback(current, backup)

    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
