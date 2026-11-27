"""Size-rotating file logger used by discovery and gateway security logs."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable


class RotatingFileLogger:
    """Append lines to a file, rotating when it exceeds ``max_bytes``."""

    def __init__(self, path: Path | str, max_bytes: int = 1_048_576, backups: int = 3) -> None:
        self.path = Path(path)
        self.max_bytes = max(4096, int(max_bytes))
        self.backups = max(0, min(10, int(backups)))
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, message: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} [{level}] {message}\n"
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                    self._rotate()
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass

    def _rotate(self) -> None:
        for index in range(self.backups - 1, 0, -1):
            src = self.path.with_suffix(f"{self.path.suffix}.{index}")
            dst = self.path.with_suffix(f"{self.path.suffix}.{index + 1}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    pass
        if self.backups:
            try:
                self.path.replace(self.path.with_suffix(f"{self.path.suffix}.1"))
            except OSError:
                pass

    def tail(self, count: int = 20) -> list[str]:
        try:
            return list(deque(self.path.read_text(encoding="utf-8", errors="replace").splitlines(), maxlen=count))
        except OSError:
            return []


def safe_source_name(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))[:60] or "unknown"


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({str(v) for v in values if str(v).strip()})
