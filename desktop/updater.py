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


def _log(message: str) -> None:
    try:
        target = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
        with open(target.parent / "updater.log", "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


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


def _looks_like_executable(path: Path) -> bool:
    """Reject truncated/corrupt downloads before touching the installed EXE."""
    try:
        if path.stat().st_size < 4096:
            return False
        with open(path, "rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
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
        _log(f"version probe exit={completed.returncode}")
        if completed.returncode != 0:
            return ""
        return version_file.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        _log(f"version probe failed: {type(exc).__name__}: {exc}")
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
            _log("rollback restored the previous executable")
    except OSError as exc:
        _log(f"rollback failed: {exc}")
    return 1


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: ProxyHunterUpdater <current_exe> <new_exe> [pid] [expected_version]")
        return 2
    current = Path(sys.argv[1])
    new = Path(sys.argv[2])
    pid = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None
    expected_version = sys.argv[4].strip() if len(sys.argv) > 4 else ""
    _log(f"start current={current} new={new} pid={pid} expected={expected_version!r}")

    # Give the main process time to release its file handles (Wine-safe).
    time.sleep(2)
    if pid is not None:
        deadline = time.monotonic() + 120
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.5)

    if not _looks_like_executable(new):
        _log("replacement is not a valid Windows executable; refusing to install")
        return 1

    backup = current.with_suffix(current.suffix + ".bak")
    try:
        if current.is_file():
            shutil.copy2(current, backup)
        shutil.copy2(new, current)
        _log("replacement copied")
    except OSError as exc:
        _log(f"copy failed: {exc}")
        return _rollback(current, backup)

    # Verify the new binary before launching the full GUI.  This catches a
    # valid-but-broken update even when the file size and hash were correct.
    if expected_version:
        reported = _reported_version(current)
        _log(f"reported version={reported!r}")
        if reported != expected_version:
            _log(f"version verification failed: expected {expected_version!r}, got {reported!r}")
            return _rollback(current, backup)

    # Launch the updated application and verify it stays alive briefly.
    try:
        proc = subprocess.Popen([str(current)], close_fds=True)
    except OSError as exc:
        _log(f"launch failed: {exc}")
        return _rollback(current, backup)

    time.sleep(8)
    if proc.poll() is not None:
        _log(f"updated application exited early with {proc.returncode}")
        return _rollback(current, backup)

    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    _log("update installed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
