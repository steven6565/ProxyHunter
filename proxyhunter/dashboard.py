"""Professional live terminal dashboard built with Rich."""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Iterable

from rich.console import Console, Group, RenderableType, Text
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .models import Proxy
from .resources import ResourceMonitor
from .utils import country_name

console = Console()


class Metrics:
    """Thread-safe counters shared by the checker and the dashboard."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.discovered = 0
        self.unique = 0
        self.working = 0
        self.dead = 0
        self.checked = 0
        self.active_workers = 0
        self.skipped = 0
        self.latency_sum = 0.0
        self.latency_count = 0
        self.countries: Counter[str] = Counter()
        self.started = time.monotonic()
        self._completions: deque[float] = deque()

    def add_discovered(self, count: int, unique: int = 0) -> None:
        with self.lock:
            self.discovered += count
            self.unique += unique

    def mark_checked(self, proxy: Proxy) -> None:
        with self.lock:
            self.checked += 1
            self._completions.append(time.monotonic())
            if proxy.working:
                self.working += 1
                self.latency_sum += proxy.response_time_ms
                self.latency_count += 1
                code = proxy.country_code or "XX"
                self.countries[code] += 1
            else:
                self.dead += 1

    def speed(self) -> float:
        """Completions per second over the last 3 seconds."""
        with self.lock:
            cutoff = time.monotonic() - 3.0
            while self._completions and self._completions[0] < cutoff:
                self._completions.popleft()
            return len(self._completions) / 3.0

    def avg_latency(self) -> float:
        with self.lock:
            return self.latency_sum / self.latency_count if self.latency_count else 0.0

    def elapsed(self) -> str:
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def reset_check_counters(self) -> None:
        with self.lock:
            self.working = 0
            self.dead = 0
            self.checked = 0
            self.skipped = 0
            self.latency_sum = 0.0
            self.latency_count = 0
            self.countries.clear()
            self._completions.clear()
            self.started = time.monotonic()


class Dashboard:
    """A Rich ``Live`` view of a discovery/validation run."""

    def __init__(self, metrics: Metrics, title: str = "Proxy Hunter") -> None:
        self.metrics = metrics
        self.title = title
        self.resources = ResourceMonitor()
        self.logs: deque[Text] = deque(maxlen=6)
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            refresh_per_second=8,
            transient=False,
        )
        self.task_id = self.progress.add_task("[cyan]Starting…", total=1)
        self.live = Live(
            self,
            console=console,
            refresh_per_second=8,
            screen=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )

    def __enter__(self) -> "Dashboard":
        self.live.start()
        return self

    def __exit__(self, *exc) -> None:
        self.live.stop()

    def log(self, message: str, style: str = "dim") -> None:
        self.logs.append(Text(f"[{self.metrics.elapsed()}] {message}", style=style))

    def set_phase(self, description: str, total: int | None = None) -> None:
        self.progress.update(self.task_id, description=description, completed=0)
        if total is not None:
            self.progress.update(self.task_id, total=max(1, total))

    def set_total(self, total: int) -> None:
        self.progress.update(self.task_id, total=max(1, total))

    def advance(self, amount: int = 1) -> None:
        self.progress.advance(self.task_id, amount)

    def __rich_console__(self, render_console, options):  # noqa: ANN001
        yield self._build()

    def _build(self) -> RenderableType:
        m = self.metrics
        cpu, ram, used_mb = self.resources.snapshot()
        cpu_s = f"{cpu:.0f}%" if cpu is not None else "n/a"
        ram_s = f"{ram:.0f}% ({used_mb:.0f} MB)" if ram is not None and used_mb is not None else "n/a"

        stats = Table.grid(expand=True, padding=(0, 1))
        stats.add_column(ratio=1)
        stats.add_column(ratio=1)
        stats.add_column(ratio=1)
        stats.add_column(ratio=1)
        stats.add_row(
            f"[bold cyan]Discovered[/] {m.discovered:,}",
            f"[bold cyan]Unique[/] {m.unique:,}",
            f"[bold green]Working[/] {m.working:,}",
            f"[bold red]Dead[/] {m.dead:,}",
        )
        stats.add_row(
            f"[bold yellow]Speed[/] {m.speed():.1f}/s",
            f"[bold yellow]Active workers[/] {m.active_workers}",
            f"[bold magenta]Avg latency[/] {m.avg_latency():.0f} ms",
            f"[bold magenta]Elapsed[/] {m.elapsed()}",
        )
        stats.add_row(
            f"[dim]CPU[/] {cpu_s}",
            f"[dim]RAM[/] {ram_s}",
            f"[dim]Skipped[/] {m.skipped:,}",
            f"[dim]Checked[/] {m.checked:,}",
        )

        top_countries = ", ".join(
            f"{code} {country_name(code)}:{count}"
            for code, count in m.countries.most_common(6)
        ) or "none yet"

        log_text = Text("\n".join(str(line) for line in self.logs)) or Text("Waiting for activity…", style="dim")

        return Group(
            Panel(stats, title=f"[bold]{self.title}[/]", border_style="bright_blue", padding=(0, 1)),
            self.progress,
            Panel(Text(top_countries, style="cyan"), title="Country distribution", border_style="blue"),
            Panel(log_text, title="Activity log", border_style="blue", height=8),
        )


def summary_table(rows: Iterable[tuple[str, str]]) -> Table:
    """Small helper for non-live summary tables in the menus."""
    table = Table(show_header=False, box=None, expand=False)
    table.add_column(style="bold cyan")
    table.add_column()
    for key, value in rows:
        table.add_row(key, str(value))
    return table
