#!/usr/bin/env python3
"""Proxy Hunter - automated proxy discovery, validation and management."""

import bootstrap

bootstrap.ensure_dependencies()

import argparse
import asyncio
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from proxyhunter import __version__
from proxyhunter.checker import Checker
from proxyhunter.resources import ResourceMonitor
from proxyhunter.config import WORKER_PRESETS, load_config, save_config
from proxyhunter.dashboard import Dashboard, Metrics
from proxyhunter.discovery import Discovery
from proxyhunter.gateway import (
    COUNTRY_OPTIONS,
    ROTATION_MODES,
    Gateway,
    HeadlessDashboard,
)
from proxyhunter.geo import GeoResolver
from proxyhunter.models import Proxy, utc_now
from proxyhunter.storage import Storage
from proxyhunter.utils import country_name, deduplicate, normalize_country_code, parse_proxy

console = Console()

BANNER = r"""
[yellow]██████╗  ██████╗ ██████╗ ███████╗███╗   ███╗██╗██╗  ██╗[/]
[yellow]██╔══██╗██╔═══██╗██╔══██╗██╔════╝████╗ ████║██║██║ ██╔╝[/]
[yellow]██████╔╝██║   ██║██████╔╝█████╗  ██╔████╔██║██║█████╔╝ [/]
[yellow]██╔═══╝ ██║   ██║██╔══██╗██╔══╝  ██║╚██╔╝██║██║██╔═██╗ [/]
[yellow]██║     ╚██████╔╝██║  ██║███████╗██║ ╚═╝ ██║██║██║  ██╗[/]
[yellow]╚═╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝╚═╝  ╚═╝[/]
[bold cyan]HUNTER[/] [dim]v{version} · discover · validate · organise[/]
"""

MENU_ITEMS = [
    ("1", "Discover Public Proxies"),
    ("2", "Check Existing Proxy List"),
    ("3", "Discover and Validate Automatically"),
    ("4", "Filter Proxies by Country"),
    ("5", "Filter Proxies by Protocol"),
    ("6", "Export Working Proxies"),
    ("7", "Configure Workers and Timeout"),
    ("8", "Recheck Saved Proxies"),
    ("9", "Automatic Refresh Mode"),
    ("G", "Rotating Proxy Gateway"),
    ("0", "Exit"),
]


class App:
    def __init__(self) -> None:
        self.config = load_config()
        self.storage = Storage(self.config)
        self.geo = GeoResolver(self.config, self.storage)
        self.metrics = Metrics()
        self.stop_event = asyncio.Event()
        self.dashboard: Dashboard | None = None
        self.gateway_events: deque[str] = deque(maxlen=12)
        self.resource_monitor = ResourceMonitor()
        self.gateway = Gateway(self.config, self.storage, self.geo, self.gateway_events)
        self.gateway.refresh_callback = self._gateway_refresh

    # -------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self.geo.close()
        self.storage.close()

    def new_dashboard(self, title: str) -> Dashboard:
        self.dashboard = Dashboard(self.metrics, title)
        return self.dashboard

    def components(self, dashboard: Dashboard) -> tuple[Discovery, Checker]:
        return (
            Discovery(self.config, self.storage, self.metrics, dashboard),
            Checker(self.config, self.storage, self.geo, self.metrics, dashboard, self.stop_event),
        )

    def install_signals(self) -> None:
        def handler() -> None:
            if not self.stop_event.is_set():
                self.stop_event.set()
                console.print("\n[yellow]Shutdown requested – finishing current work…[/]")

        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, handler)
            return
        except (NotImplementedError, RuntimeError, AttributeError):
            pass
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: handler())
            except (ValueError, OSError):
                pass

    # ------------------------------------------------------------------ output
    def show_banner(self) -> None:
        console.print(Panel(BANNER.format(version=__version__), border_style="bright_blue", padding=(0, 1)))
        console.print(
            "[dim]Workers:[/] [bold cyan]{workers}[/]  [dim]Timeout:[/] [bold cyan]{timeout}s[/]  "
            "[dim]Rate limit:[/] [bold cyan]{rate}/s[/]  [dim]GeoIP:[/] [bold cyan]{geo}[/]".format(
                workers=self.config["workers"]["count"],
                timeout=self.config["timeout_seconds"],
                rate=self.config["rate_limit_per_second"],
                geo=self.geo.backend,
            )
        )

    def show_menu(self) -> None:
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style="bold yellow", width=3)
        table.add_column()
        for key, label in MENU_ITEMS:
            table.add_row(key, label)
        console.print(Panel(table, title="[bold]Main menu[/]", border_style="blue", expand=False))

    def show_summary(self, title: str = "Run summary") -> None:
        m = self.metrics
        table = Table(box=None, show_header=False)
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("Discovered", f"{m.discovered:,}")
        table.add_row("Unique", f"{m.unique:,}")
        table.add_row("Checked", f"{m.checked:,}")
        table.add_row("Working", f"[green]{m.working:,}[/]")
        table.add_row("Dead", f"[red]{m.dead:,}[/]")
        table.add_row("Average latency", f"{m.avg_latency():.0f} ms")
        table.add_row("Elapsed", m.elapsed())
        table.add_row("Working in database", f"{self.storage.count_working():,}")
        console.print(Panel(table, title=f"[bold]{title}[/]", border_style="green", expand=False))

    def show_proxy_table(self, proxies: list[Proxy], limit: int = 18) -> None:
        if not proxies:
            console.print("[yellow]No matching working proxies.[/]")
            return
        table = Table(title=f"Working proxies (showing {min(limit, len(proxies))} of {len(proxies)})")
        for column in ("#", "Address", "Protocol", "Latency", "Country", "City", "ISP"):
            table.add_column(column, style="cyan" if column == "#" else None)
        for index, proxy in enumerate(proxies[:limit], 1):
            table.add_row(
                str(index), proxy.address, proxy.protocol,
                f"{proxy.response_time_ms:.0f} ms",
                f"{proxy.country_code} {country_name(proxy.country_code, proxy.country)}".strip(),
                proxy.city or "-", proxy.isp[:28] or "-",
            )
        console.print(table)

    # ------------------------------------------------------------------- flows
    async def discover_only(self) -> None:
        with self.new_dashboard("Proxy Hunter · Discovery") as dash:
            discovery, _ = self.components(dash)
            proxies = await discovery.discover()
        console.print(f"[green]Saved {len(proxies)} unique candidates to output/discovered_proxies.txt[/]")

    async def check_list(self, proxies: list[Proxy], title: str = "Proxy Hunter · Validation") -> list[Proxy]:
        if not proxies:
            console.print("[yellow]Nothing to check.[/]")
            return []
        with self.new_dashboard(title) as dash:
            _, checker = self.components(dash)
            results = await checker.check(proxies)
        counts = self.storage.export_all()
        self.show_summary()
        console.print(
            "[dim]Exported[/] " + " · ".join(
                f"{name}: {value}" for name, value in counts.items()
                if name in ("working_proxies.txt", "working_proxies.json", "working_proxies.csv")
            )
        )
        return results

    async def discover_and_validate(self) -> None:
        with self.new_dashboard("Proxy Hunter · Discover + Validate") as dash:
            discovery, checker = self.components(dash)
            proxies = await discovery.discover()
            if not proxies:
                console.print("[yellow]No candidates discovered.[/]")
                return
            await checker.check(proxies)
        self.storage.export_all()
        self.show_summary("Discovery + validation")

    # ------------------------------------------------------------ menu actions
    async def action_check_existing(self) -> None:
        path = Path("output/discovered_proxies.txt")
        if not path.exists():
            path = Path("output/working_proxies.txt")
        answer = Prompt.ask("[cyan]Proxy list file[/]", default=str(path))
        path = Path(answer).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if not path.is_file():
            console.print(f"[red]File not found:[/] {path}")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        proxies = deduplicate(
            p for line in text.splitlines()
            if (p := parse_proxy(line)) is not None
        )
        console.print(f"[cyan]Loaded {len(proxies)} candidates from {path.name}[/]")
        await self.check_list(proxies, "Proxy Hunter · Checking list")

    async def action_filter_country(self) -> None:
        proxies = self.storage.get_working()
        if not proxies:
            console.print("[yellow]No working proxies saved yet. Run discovery first.[/]")
            return
        counts: dict[str, int] = {}
        for proxy in proxies:
            code = normalize_country_code(proxy.country_code) or "XX"
            counts[code] = counts.get(code, 0) + 1
        top = ", ".join(f"{code} ({country_name(code)}): {n}" for code, n in sorted(counts.items(), key=lambda x: -x[1])[:12])
        console.print(f"[dim]Available countries:[/] {top}")
        answer = Prompt.ask("[cyan]Country code(s), comma separated or 'all'[/]", default="all")
        if answer.strip().lower() == "all":
            chosen = proxies
            name = "all_countries"
        else:
            codes = {normalize_country_code(part) for part in answer.replace(" ", "").split(",") if part}
            chosen = [p for p in proxies if normalize_country_code(p.country_code) in codes]
            name = "country_" + "_".join(sorted(codes)) if codes else "country_none"
        self.show_proxy_table(chosen)
        path = self.storage.export_filtered(chosen, name)
        console.print(f"[green]Exported {len(chosen)} proxies to {path}[/]")
        if answer.strip().lower() != "all" and Prompt.ask("[cyan]Save as default country filter?[/]", choices=["y", "n"], default="n") == "y":
            self.config["country_filter"] = sorted(codes)
            save_config(self.config)
            console.print("[green]Configuration saved.[/]")

    async def action_filter_protocol(self) -> None:
        proxies = self.storage.get_working()
        if not proxies:
            console.print("[yellow]No working proxies saved yet. Run discovery first.[/]")
            return
        console.print("[dim]Available:[/] " + ", ".join(
            f"{proto}: {sum(1 for p in proxies if p.protocol == proto)}"
            for proto in ("http", "https", "socks4", "socks5")
        ))
        answer = Prompt.ask(
            "[cyan]Protocol[/]", choices=["http", "https", "socks4", "socks5", "all"], default="all"
        )
        chosen = proxies if answer == "all" else [p for p in proxies if p.protocol == answer]
        self.show_proxy_table(chosen)
        path = self.storage.export_filtered(chosen, "protocol_" + answer)
        console.print(f"[green]Exported {len(chosen)} proxies to {path}[/]")

    async def action_export(self) -> None:
        counts = self.storage.export_all()
        table = Table(title="Exported files")
        table.add_column("File")
        table.add_column("Entries", justify="right")
        for name, value in counts.items():
            table.add_row(name, str(value))
        console.print(table)
        console.print("[dim]Output directory:[/] " + str(self.storage.root))

    async def action_configure(self) -> None:
        current = self.config
        console.print(
            f"[dim]Current:[/] preset={current['workers']['preset']}, "
            f"workers={current['workers']['count']}, timeout={current['timeout_seconds']}s, "
            f"retries={current['retries']}, rate={current['rate_limit_per_second']}/s, "
            f"format={current['export_format']}"
        )
        console.print("[cyan]Presets:[/] 1) low (10)  2) normal (50)  3) fast (100)  4) high (200)  5) advanced (500)  6) custom")
        choice = Prompt.ask("[cyan]Choose preset[/]", choices=[str(i) for i in range(1, 7)], default="2")
        if choice == "6":
            count = int(Prompt.ask("[cyan]Custom worker count (1-2000)[/]", default=str(current["workers"]["count"])))
            count = max(1, min(2000, count))
            current["workers"] = {"preset": "custom", "count": count}
        else:
            preset = list(WORKER_PRESETS)[int(choice) - 1]
            current["workers"] = {"preset": preset, "count": WORKER_PRESETS[preset]}
        for key, label, cast, low, high in (
            ("timeout_seconds", "Connection timeout in seconds", float, 1.0, 120.0),
            ("retries", "Retry attempts", int, 0, 10),
            ("rate_limit_per_second", "Validation requests per second (0 = unlimited)", float, 0.0, 1000.0),
        ):
            answer = Prompt.ask(f"[cyan]{label}[/]", default=str(current[key]))
            try:
                current[key] = max(low, min(high, cast(answer)))
            except ValueError:
                console.print("[yellow]Invalid number, keeping previous value.[/]")
        fmt = Prompt.ask("[cyan]Export format[/]", choices=["ip_port", "protocol_url"], default=current["export_format"])
        current["export_format"] = fmt
        save_config(current)
        console.print(f"[green]Configuration saved: {current['workers']['count']} workers, {current['timeout_seconds']}s timeout.[/]")

    async def action_recheck(self) -> None:
        proxies = self.storage.get_working()
        if not proxies:
            console.print("[yellow]No saved working proxies to recheck.[/]")
            return
        console.print(f"[cyan]Rechecking {len(proxies)} saved proxies…[/]")
        await self.check_list(proxies, "Proxy Hunter · Recheck")

    async def action_refresh(self) -> None:
        console.print("[cyan]Refresh intervals:[/] 1) 5 min  2) 15 min  3) 30 min  4) 60 min  5) custom")
        choice = Prompt.ask("[cyan]Choose interval[/]", choices=[str(i) for i in range(1, 6)], default="2")
        minutes = {1: 5, 2: 15, 3: 30, 4: 60}.get(int(choice))
        if minutes is None:
            minutes = float(Prompt.ask("[cyan]Custom interval in minutes[/]", default="15"))
        self.config["refresh_mode"]["interval_minutes"] = minutes
        save_config(self.config)
        console.print(f"[green]Automatic refresh every {minutes} minutes. Press Ctrl+C to stop.[/]")

        cycle = 0
        while not self.stop_event.is_set():
            cycle += 1
            started = utc_now()
            console.print(f"\n[bold cyan]=== Refresh cycle {cycle} started at {started} ===[/]")
            try:
                with self.new_dashboard(f"Proxy Hunter · Refresh #{cycle}") as dash:
                    discovery, checker = self.components(dash)
                    proxies = await discovery.discover()
                    if self.config["refresh_mode"].get("auto_recheck", True):
                        saved = self.storage.get_working()
                        combined = deduplicate([*saved, *proxies])
                        if combined:
                            await checker.check(combined)
                    if self.config["refresh_mode"].get("auto_discover", True) and not self.config["refresh_mode"].get("auto_recheck", True):
                        await checker.check(proxies)
                removed = self.storage.prune_expired(int(self.config["refresh_mode"]["remove_expired_hours"]))
                counts = self.storage.export_all()
                console.print(
                    f"[green]Cycle {cycle} complete:[/] {self.storage.count_working():,} working, "
                    f"{removed} expired removed, {counts['working_proxies.txt']} exported."
                )
                self.show_summary(f"Refresh #{cycle}")
            except Exception as exc:  # noqa: BLE001 - keep the refresh loop alive
                console.print(f"[red]Refresh cycle failed:[/] {exc}")
            if self.stop_event.is_set():
                break
            seconds = minutes * 60
            console.print(f"[dim]Next refresh in {minutes} minute(s)…[/]")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass
        console.print("[yellow]Automatic refresh stopped.[/]")

    # ----------------------------------------------------------------- gateway
    def gateway_status_panel(self) -> Panel:
        g = self.gateway
        s = g.snapshot()
        cpu, ram, used_mb = self.resource_monitor.snapshot()
        cpu_s = f"{cpu:.0f}%" if cpu is not None else "n/a"
        ram_s = f"{ram:.0f}% ({used_mb:.0f} MB)" if ram is not None and used_mb is not None else "n/a"
        status_style = "green" if g.running else "red"
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_row(
            f"[bold]Status[/] [{status_style}]{s['status']}[/]",
            f"[bold]Endpoint[/] {s['endpoint']}",
            f"[bold]Version[/] v{s['version']} · uptime {s['uptime']}",
        )
        table.add_row(
            f"[bold]Country[/] {s['country'].upper()}",
            f"[bold]Rotation[/] {s['mode']}",
            f"[bold]Current IP[/] {s['current_ip']}",
        )
        table.add_row(
            f"[green]Eligible[/] {s['healthy']} / {s['total']}",
            f"[bold]Unique exit IPs[/] {s['unique_ips']}",
            f"[yellow]Quarantined[/] {s['quarantined']} · [red]expired[/] {s['failed']}",
        )
        table.add_row(
            f"[bold]Connections[/] {s['active']} active",
            f"[green]OK[/] {s['success']} · [red]failed[/] {s['requests_failed']}",
            f"[bold]Rotations[/] {s['rotations']} · [bold]Latency[/] {s['latency']:.0f} ms",
        )
        table.add_row(
            f"[dim]CPU[/] {cpu_s}",
            f"[dim]RAM[/] {ram_s}",
            f"[dim]Refresh[/] {s['last_refresh']} · health {s['last_health']}",
        )
        warning = g.capacity_warning() or (
            "WARNING: no eligible proxy — connections will fail closed" if s["capacity_warning"] else ""
        )
        if warning:
            table.add_row(f"[bold red]{warning}[/]", "", "")
        return Panel(table, title="[bold]Rotating Proxy Gateway · v2.0[/]", border_style="bright_blue")

    def _gateway_log_panel(self) -> Panel:
        recent = list(self.gateway_events)[-4:]
        body = Text("\n".join(recent)) if recent else Text("No gateway events yet.", style="dim")
        return Panel(body, title="Gateway log", border_style="blue", height=6)

    async def action_gateway_country(self) -> None:
        capacity = self.gateway.available_countries()
        console.print("[cyan]Available verified proxy counts by country:[/]")
        if capacity:
            console.print(
                ", ".join(f"{code} ({country_name(code)}): {n}" for code, n in sorted(capacity.items()))
            )
        else:
            console.print("[yellow]No recently validated proxies in the pool.[/]")
        console.print(
            "[cyan]1[/] All  [cyan]2[/] US  [cyan]3[/] GB  [cyan]4[/] IN  "
            "[cyan]5[/] DE  [cyan]6[/] CA  [cyan]7[/] Custom (comma-separated codes)  [cyan]0[/] Back"
        )
        choice = Prompt.ask(
            "[cyan]Select country[/]", choices=["1", "2", "3", "4", "5", "6", "7", "0"], default="0"
        )
        mapping = {"1": "all", "2": "US", "3": "GB", "4": "IN", "5": "DE", "6": "CA"}
        selection = mapping.get(choice)
        if choice == "7":
            selection = Prompt.ask(
                "[cyan]ISO country codes (e.g. US,GB,IN)[/]",
                default=",".join(sorted(capacity)[:2]) if capacity else "US",
            )
        if selection:
            ok, warning = self.gateway.set_countries(selection)
            if not ok:
                console.print("[red]Invalid country selection.[/]")
                return
            console.print(f"[green]Selected countries:[/] {self.gateway.country_label.upper()}")
            if warning:
                console.print(f"[bold red]{warning}[/]")
            else:
                console.print("[dim]Eligible proxies exist for the selection.[/]")

    async def action_gateway_mode(self) -> None:
        console.print("[cyan]Rotation modes:[/] " + ", ".join(ROTATION_MODES))
        mode = Prompt.ask("[cyan]Rotation mode[/]", choices=list(ROTATION_MODES), default=self.gateway.mode)
        self.gateway.set_mode(mode)
        self.gateway.reset_rotation()
        console.print(f"[green]Rotation mode set to {mode}.[/]")

    async def action_gateway_settings(self) -> None:
        cfg = self.config["gateway"]
        console.print("[dim]Gateway settings (press Enter to keep the current value)[/]")
        cfg["bind"] = Prompt.ask("[cyan]Bind address[/]", default=cfg["bind"])
        cfg["port"] = int(Prompt.ask("[cyan]Port[/]", default=str(cfg["port"])))
        cfg["rotation_seconds"] = int(Prompt.ask("[cyan]Time-based rotation seconds[/]", default=str(cfg["rotation_seconds"])))
        cfg["max_retries"] = int(Prompt.ask("[cyan]Upstream retries[/]", default=str(cfg["max_retries"])))
        cfg["connect_timeout_seconds"] = float(Prompt.ask("[cyan]Upstream connect timeout (s)[/]", default=str(cfg["connect_timeout_seconds"])))
        cfg["failure_threshold"] = int(Prompt.ask("[cyan]Failures before removing an upstream[/]", default=str(cfg["failure_threshold"])))
        cfg["pool_refresh_minutes"] = int(Prompt.ask("[cyan]Pool refresh interval (min)[/]", default=str(cfg["pool_refresh_minutes"])))
        cfg["health_check_minutes"] = int(Prompt.ask("[cyan]Health check interval (min)[/]", default=str(cfg["health_check_minutes"])))
        security = cfg.setdefault("security", {})
        security["destination_policy"] = Prompt.ask(
            "[cyan]Destination policy[/]", choices=["deny_private", "allowlist", "all"],
            default=security.get("destination_policy", "deny_private"),
        )
        security["destination_allowlist"] = [
            x.strip() for x in Prompt.ask(
                "[cyan]Destination allowlist (comma separated, blank = none)[/]",
                default=",".join(security.get("destination_allowlist") or []),
            ).split(",") if x.strip()
        ]
        security["ip_allowlist"] = [
            x.strip() for x in Prompt.ask(
                "[cyan]Client IP allowlist (CIDR, comma separated, blank = any)[/]",
                default=",".join(security.get("ip_allowlist") or []),
            ).split(",") if x.strip()
        ]
        security["max_connections"] = int(Prompt.ask("[cyan]Max simultaneous connections[/]", default=str(security.get("max_connections", 200))))
        security["max_connections_per_user"] = int(Prompt.ask("[cyan]Max connections per user[/]", default=str(security.get("max_connections_per_user", 10))))
        security["rate_limit_per_second"] = float(Prompt.ask("[cyan]Per-client request rate limit (0 = unlimited)[/]", default=str(security.get("rate_limit_per_second", 0))))
        tls = security.setdefault("tls", {"enabled": False, "certfile": "", "keyfile": ""})
        tls["enabled"] = Prompt.ask("[cyan]Enable TLS on gateway listener?[/]", choices=["y", "n"], default="y" if tls.get("enabled") else "n") == "y"
        if tls["enabled"]:
            tls["certfile"] = Prompt.ask("[cyan]TLS certificate path[/]", default=tls.get("certfile") or "")
            tls["keyfile"] = Prompt.ask("[cyan]TLS private key path[/]", default=tls.get("keyfile") or "")

        enable_auth = Prompt.ask(
            "[cyan]Require proxy authentication?[/]", choices=["y", "n"],
            default="y" if cfg["auth"].get("enabled") else "n",
        ) == "y"
        if enable_auth:
            username = Prompt.ask("[cyan]Username[/]", default=cfg["auth"].get("username") or "")
            password = Prompt.ask("[cyan]New password (blank keeps existing hash)[/]", default="")
            if username and password:
                self.gateway.security.set_credentials(username, password)
            else:
                cfg["auth"]["enabled"] = True
                cfg["auth"]["username"] = username
            cfg["allow_remote_access"] = Prompt.ask(
                "[red]Allow non-localhost binding? (requires auth)[/]", choices=["y", "n"],
                default="y" if cfg.get("allow_remote_access") else "n",
            ) == "y"
        else:
            cfg["auth"]["enabled"] = False
            cfg["allow_remote_access"] = False
        save_config(self.config)
        console.print(
            "[green]Gateway settings saved (credentials stored as PBKDF2 hashes). "
            "Restart the gateway to apply bind/port/TLS/auth changes.[/]"
        )

    async def action_gateway_monitor(self) -> None:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Gateway live[/]"),
            BarColumn(bar_width=36),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            refresh_per_second=8,
        )
        task_id = progress.add_task("starting…", total=100, completed=0)
        console.print("[dim]Live monitor — press Enter to return to the gateway menu.[/]")
        stop_monitor = asyncio.Event()
        loop = asyncio.get_running_loop()

        def wait_for_enter() -> None:
            try:
                input()
            except Exception:  # noqa: BLE001
                pass
            loop.call_soon_threadsafe(stop_monitor.set)

        threading.Thread(target=wait_for_enter, daemon=True).start()
        with Live(console=console, refresh_per_second=8, screen=False) as live:
            while not stop_monitor.is_set() and not self.stop_event.is_set():
                g = self.gateway
                s = g.snapshot()
                cpu, ram, _ = self.resource_monitor.snapshot()
                cpu_s = f"CPU {cpu:.0f}%" if cpu is not None else "CPU n/a"
                ram_s = f"RAM {ram:.0f}%" if ram is not None else "RAM n/a"
                progress.update(
                    task_id,
                    completed=int(time.monotonic() * 12) % 100,
                    description=(
                        f"v{s['version']} · {s['status']} · {s['endpoint']} · "
                        f"{s['healthy']}/{s['total']} eligible · {s['unique_ips']} IPs · "
                        f"{s['active']} active · {s['current_ip']} · {cpu_s} · {ram_s} · {s['uptime']}"
                    ),
                )
                warning = g.capacity_warning()
                live.update(
                    Group(
                        Panel(
                            progress,
                            title=f"[bold]Gateway Live · {s['mode']} · {s['country'].upper()}[/]",
                            border_style="bright_blue",
                        ),
                        Text(warning, style="bold red") if warning else Text(""),
                    )
                )
                await asyncio.sleep(0.15)

    async def action_gateway(self) -> None:
        while not self.stop_event.is_set():
            self.gateway.reload_pool()
            console.print(self.gateway_status_panel())
            console.print(self._gateway_log_panel())
            console.print(
                "[cyan]1[/] Start  [cyan]2[/] Stop  [cyan]3[/] Restart  "
                "[cyan]4[/] Countries  [cyan]5[/] Rotation  [cyan]6[/] Settings  "
                "[cyan]7[/] Live monitor  [cyan]8[/] Health now  [cyan]9[/] Refresh now  [cyan]0[/] Back"
            )
            choice = Prompt.ask(
                "[bold cyan]Gateway[/]",
                choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"], default="0",
            )
            if choice == "0":
                break
            if choice == "1":
                await self.gateway.start()
            elif choice == "2":
                await self.gateway.stop()
            elif choice == "3":
                await self.gateway.restart()
            elif choice == "4":
                await self.action_gateway_country()
            elif choice == "5":
                await self.action_gateway_mode()
            elif choice == "6":
                await self.action_gateway_settings()
            elif choice == "7":
                await self.action_gateway_monitor()
            elif choice == "8":
                result = await self.gateway.run_health_cycle()
                console.print(f"[green]Health cycle:[/] {result}")
            elif choice == "9":
                await self.gateway.run_pool_refresh_cycle()
                console.print("[green]Pool refresh complete.[/]")

    async def _gateway_refresh(self) -> None:
        """Bounded discovery + validation used by the gateway background loop."""
        events = self.gateway_events
        dash = HeadlessDashboard(events)
        metrics = Metrics()
        discovery = Discovery(self.config, self.storage, metrics, dash)
        cfg = dict(self.config)
        cfg["max_proxies_to_check"] = int(self.config["gateway"]["refresh_check_limit"])
        cfg["protocol_filter"] = []
        cfg["country_filter"] = []
        checker = Checker(cfg, self.storage, self.geo, metrics, dash, self.gateway.stop_event)
        candidates = await discovery.discover()
        combined = deduplicate([*self.storage.get_working(), *candidates])[:cfg["max_proxies_to_check"]]
        results = await checker.check(combined)
        dash.log(f"gateway refresh: {sum(p.working for p in results)} healthy of {len(results)} checked")

    # -------------------------------------------------------------- main loop
    async def run(self) -> None:
        self.install_signals()
        self.show_banner()
        handlers = {
            "1": self.discover_only,
            "2": self.action_check_existing,
            "3": self.discover_and_validate,
            "4": self.action_filter_country,
            "5": self.action_filter_protocol,
            "6": self.action_export,
            "7": self.action_configure,
            "8": self.action_recheck,
            "9": self.action_refresh,
            "G": self.action_gateway,
        }
        while not self.stop_event.is_set():
            self.show_menu()
            try:
                choice = Prompt.ask("[bold cyan]Select[/]", choices=[key for key, _ in MENU_ITEMS], default="0")
            except (KeyboardInterrupt, EOFError):
                self.stop_event.set()
                break
            if choice == "0":
                break
            try:
                await handlers[choice]()
            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Interrupted. Saved results are preserved.[/]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Error:[/] {type(exc).__name__}: {exc}")
        console.print("[dim]Goodbye.[/]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Proxy Hunter - automated proxy discovery and validation")
    parser.add_argument("--check", metavar="FILE", help="check proxies from a text file and exit")
    parser.add_argument("--discover", action="store_true", help="discover proxies and exit")
    parser.add_argument("--auto", action="store_true", help="discover, validate, export and exit")
    parser.add_argument("--export", action="store_true", help="re-export saved working proxies and exit")
    parser.add_argument("--gateway", action="store_true", help="start the rotating gateway (runs until Ctrl+C)")
    parser.add_argument("--workers", type=int, help="override worker count for this run")
    parser.add_argument("--timeout", type=float, help="override timeout (seconds) for this run")
    return parser.parse_args()


async def cli(app: App, args: argparse.Namespace) -> None:
    app.install_signals()
    if args.workers:
        app.config["workers"] = {"preset": "custom", "count": max(1, min(2000, args.workers))}
    if args.timeout:
        app.config["timeout_seconds"] = max(1.0, float(args.timeout))
    app.show_banner()
    if getattr(args, "gateway", False):
        if await app.gateway.start():
            console.print(
                f"[green]Rotating gateway listening on http://{app.gateway.bind}:{app.gateway.port}[/]\n"
                "[dim]Press Ctrl+C to stop.[/]"
            )
            while not app.stop_event.is_set():
                await asyncio.sleep(0.5)
    elif args.discover:
        await app.discover_only()
    elif args.auto:
        await app.discover_and_validate()
    elif args.export:
        await app.action_export()
    elif args.check:
        path = Path(args.check).expanduser()
        text = path.read_text(encoding="utf-8", errors="replace")
        proxies = deduplicate(p for line in text.splitlines() if (p := parse_proxy(line)) is not None)
        console.print(f"[cyan]Loaded {len(proxies)} proxies from {path}[/]")
        await app.check_list(proxies)
    else:
        await app.run()


def main() -> None:
    args = parse_args()
    app = App()

    async def runner() -> None:
        try:
            await cli(app, args)
        finally:
            if app.gateway.running:
                await app.gateway.stop()

    try:
        asyncio.run(runner())
    finally:
        app.close()


if __name__ == "__main__":
    main()
