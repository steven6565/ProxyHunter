"""Cross-platform CPU / memory sampling.

psutil is used when installed (all desktop platforms). On Android/Termux --
where psutil frequently cannot be compiled -- we fall back to /proc, which is
available and costs almost nothing.
"""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - depends on the host platform
    import psutil  # type: ignore
except Exception:  # noqa: BLE001 - any import failure means "use fallback"
    psutil = None  # type: ignore


class ResourceMonitor:
    def __init__(self) -> None:
        self._prev_cpu: tuple[int, int] | None = None
        has_proc = Path("/proc/meminfo").exists() or Path("/proc/stat").exists()
        self.backend = "psutil" if psutil is not None else ("proc" if has_proc else "none")

    def snapshot(self) -> tuple[float | None, float | None, float | None]:
        """Return ``(cpu_percent, ram_percent, used_ram_mb)``.

        Any value may be ``None`` when the platform cannot provide it.
        """
        if psutil is not None:
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                return float(cpu), float(mem.percent), float(mem.used) / (1024 * 1024)
            except Exception:  # noqa: BLE001
                pass

        if self.backend == "proc":
            return self._from_proc()

        return None, None, None

    def _from_proc(self) -> tuple[float | None, float | None, float | None]:
        cpu: float | None = None
        ram: float | None = None
        used_mb: float | None = None
        try:
            parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
            values = [int(x) for x in parts]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            if self._prev_cpu is not None:
                prev_idle, prev_total = self._prev_cpu
                d_total = total - prev_total
                d_idle = idle - prev_idle
                if d_total > 0:
                    cpu = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
            self._prev_cpu = (idle, total)
        except Exception:  # noqa: BLE001
            pass

        try:
            info: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, _, rest = line.partition(":")
                info[key] = int(rest.strip().split()[0])
            total_kb = info.get("MemTotal", 0)
            avail_kb = info.get("MemAvailable", info.get("MemFree", 0))
            if total_kb > 0:
                used_kb = max(0, total_kb - avail_kb)
                ram = used_kb / total_kb * 100.0
                used_mb = used_kb / 1024.0
        except Exception:  # noqa: BLE001
            pass

        return cpu, ram, used_mb
