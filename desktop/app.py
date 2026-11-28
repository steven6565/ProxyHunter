#!/usr/bin/env python3
"""ProxyHunter v4.0.0 Windows desktop application (Tkinter, modern UI)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT, ROOT / "backend", ROOT / "shared"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _selftest_requested() -> bool:
    """True for ``--selftest`` or ``PROXYHUNTER_SELFTEST=1``."""
    if os.environ.get("PROXYHUNTER_SELFTEST", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return any(str(arg).lower() in ("--selftest", "/selftest") for arg in sys.argv[1:])


# Handle non-GUI modes before importing Tkinter, the GUI, the updater or the
# remote-controller stack.  This keeps the packaged EXE completely
# non-interactive and prevents modal dialogs/background threads from hanging CI.
if __name__ == "__main__" and "--version" in sys.argv:
    _version_file = Path(os.environ.get("PROXYHUNTER_VERSION_FILE", "version.txt"))
    _version_file.write_text("4.0.0", encoding="utf-8")
    raise SystemExit(0)

if __name__ == "__main__" and _selftest_requested():
    from selftest_mode import run_selftest

    raise SystemExit(run_selftest())

import json
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from backend.remote_controller import RemoteBackendController, RemoteBackendWorker, load_connection, save_connection
from shared.exports import default_export_dir, export_history, suggested_name, delete_export, export_proxies
from proxyhunter.models import Proxy

# --------------------------------------------------------------------------- theme
NAVY = "#0B1220"
CHARCOAL = "#111827"
SURFACE = "#182236"
SURFACE2 = "#1F2A44"
ACCENT = "#3B82F6"
PURPLE = "#8B5CF6"
GREEN = "#10B981"
ORANGE = "#F59E0B"
RED = "#EF4444"
MUTED = "#94A3B8"
TEXT = "#E6EDF3"

COUNTRY_FLAGS = {
    "US": "🇺🇸", "IN": "🇮🇳", "GB": "🇬🇧", "DE": "🇩🇪", "FR": "🇫🇷",
    "CA": "🇨🇦", "AU": "🇦🇺", "JP": "🇯🇵", "CN": "🇨🇳", "RU": "🇷🇺",
    "BR": "🇧🇷", "NL": "🇳🇱", "SG": "🇸🇬", "KR": "🇰🇷", "IT": "🇮🇹",
    "ES": "🇪🇸", "SE": "🇸🇪", "CH": "🇨🇭", "TR": "🇹🇷", "PL": "🇵🇱",
    "UA": "🇺🇦", "ID": "🇮🇩", "TH": "🇹🇭", "VN": "🇻🇳", "PH": "🇵🇭",
    "MY": "🇲🇾", "ZA": "🇿🇦", "AE": "🇦🇪", "SA": "🇸🇦", "IL": "🇮🇱",
    "MX": "🇲🇽", "AR": "🇦🇷", "CL": "🇨🇱", "CO": "🇨🇴", "PE": "🇵🇪",
    "EG": "🇪🇬", "NG": "🇳🇬", "KE": "🇰🇪", "PK": "🇵🇰", "BD": "🇧🇩",
}

SECTIONS = [
    "Dashboard", "Proxy List", "Rotating Gateway", "Downloads", "Settings", "About",
]


class ProxyHunterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProxyHunter v4.0.0")
        self.geometry("1280x800")
        self.minsize(1000, 640)
        self.configure(bg=CHARCOAL)
        self.events: queue.Queue = queue.Queue()
        conn = load_connection()
        if not conn.get("url"):
            self._connection_setup()
            conn = load_connection()
        self.controller = RemoteBackendController(on_event=lambda k, d: self.events.put((k, d)),
                                                url=conn.get("url", ""), api_key=conn.get("api_key", ""))
        self.worker = RemoteBackendWorker(self.controller)
        self.pending: list = []
        threading.Thread(target=self._stats_loop, daemon=True).start()
        self.dark = True
        self.export_dir = default_export_dir(desktop=True)
        self._pending_update = None
        self._pending_update_version = ""
        self._styles()
        self._layout()
        self._bind_keys()
        self.after(200, self._poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.controller.config.get("auto_update", True):
            threading.Thread(target=self._auto_update_loop, daemon=True).start()

    def _connection_setup(self) -> None:
        import os
        url = os.environ.get("PROXYHUNTER_BACKEND_URL")
        if url:
            save_connection(url, os.environ.get("PROXYHUNTER_API_KEY", ""))
            return
        import tkinter.simpledialog as sd
        url = sd.askstring("Backend connection", "Enter backend HTTPS URL:", initialvalue="https://")
        if not url:
            url = ""
        key = sd.askstring("Backend connection", "Enter API key:", show="*")
        if key is None:
            key = ""
        save_connection(url, key)

    def _stats_loop(self) -> None:
        import asyncio
        while True:
            try:
                asyncio.run(self.controller.refresh_stats())
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)

    # ---------------------------------------------------------------- styling
    def _styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=CHARCOAL)
        style.configure("Side.TFrame", background=NAVY)
        style.configure("Card.TFrame", background=SURFACE, relief="flat")
        style.configure("TLabel", background=CHARCOAL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=CHARCOAL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=CHARCOAL, foreground=TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("Good.TLabel", background=CHARCOAL, foreground=GREEN, font=("Segoe UI", 10, "bold"))
        style.configure("Bad.TLabel", background=CHARCOAL, foreground=RED, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=ACCENT, foreground="white", borderwidth=0, padding=10, font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#2563EB")])
        style.configure("Secondary.TButton", background=SURFACE2, foreground=TEXT, borderwidth=0, padding=8)
        style.map("Secondary.TButton", background=[("active", "#2A3A5E")])
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT)
        style.configure("TCombobox", fieldbackground=SURFACE, foreground=TEXT)
        style.configure("Treeview", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT, rowheight=26, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=SURFACE2, foreground=TEXT, font=("Segoe UI", 9, "bold"))
        style.configure("TProgressbar", background=GREEN, troughcolor=NAVY)
        style.configure("TCheckbutton", background=CHARCOAL, foreground=TEXT)

    # ---------------------------------------------------------------- layout
    def _layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        side = ttk.Frame(self, style="Side.TFrame", width=200)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        ttk.Label(side, text="◈ ProxyHunter", style="Title.TLabel", font=("Segoe UI", 16, "bold")).pack(pady=(22, 4))
        ttk.Label(side, text="v4.0.0", style="Muted.TLabel").pack(pady=(0, 16))
        self.nav = tk.Listbox(side, bg=NAVY, fg=TEXT, selectbackground=ACCENT, selectforeground="white",
                              borderwidth=0, highlightthickness=0, font=("Segoe UI", 11), activestyle="none")
        self.nav.pack(fill="both", expand=True, padx=10)
        for s in SECTIONS:
            self.nav.insert("end", "   " + s)
        self.nav.selection_set(0)
        self.nav.bind("<<ListboxSelect>>", self._on_nav)
        self.status_dot = tk.Label(side, text="● Ready", bg=NAVY, fg=GREEN, font=("Segoe UI", 9, "bold"))
        self.status_dot.pack(side="bottom", pady=12)

        self.content = ttk.Frame(self, padding=16)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)
        self.header = ttk.Label(self.content, text="Dashboard", style="Title.TLabel")
        self.header.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.body = ttk.Frame(self.content)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.frames = {name: self._build_section(name) for name in SECTIONS}
        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")
        self._show("Dashboard")

    def _card(self, parent, title=None, color=SURFACE):
        card = tk.Frame(parent, bg=color, bd=0, highlightthickness=0)
        card.pack(fill="x", pady=6, padx=2)
        if title:
            tk.Label(card, text=title, bg=color, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(10, 6))
        return card

    def _build_section(self, name):
        frame = ttk.Frame(self.body)
        if name == "Dashboard":
            self._build_dashboard(frame)
        elif name == "Proxy List":
            self._build_proxy_list(frame)
        elif name == "Rotating Gateway":
            self._build_gateway(frame)
        elif name == "Downloads":
            self._build_downloads(frame)
        elif name == "Settings":
            self._build_settings(frame)
        else:
            self._build_about(frame)
        return frame

    # --------------------------------------------------------------- dashboard
    def _build_dashboard(self, frame):
        top = tk.Frame(frame, bg=CHARCOAL)
        top.pack(fill="x")
        self.stat_cards = {}
        stats = [
            ("Discovered", "discovered", ACCENT), ("Working", "working", GREEN),
            ("Unique IPs", "unique", PURPLE), ("Checked", "checked", ACCENT),
            ("Failed", "dead", RED), ("Countries", "countries_count", ORANGE),
            ("Active Workers", "active_workers", GREEN), ("Avg Latency", "avg_latency", ACCENT),
        ]
        for i, (label, key, color) in enumerate(stats):
            card = tk.Frame(top, bg=SURFACE, bd=0)
            card.grid(row=i // 4, column=i % 4, padx=6, pady=6, sticky="nsew")
            top.columnconfigure(i % 4, weight=1)
            tk.Label(card, text=label, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
            val = tk.Label(card, text="0", bg=SURFACE, fg=color, font=("Segoe UI", 22, "bold"))
            val.pack(anchor="w", padx=14, pady=(0, 10))
            self.stat_cards[key] = val
        # progress
        pc = tk.Frame(frame, bg=CHARCOAL)
        pc.pack(fill="x", pady=8)
        tk.Label(pc, text="Progress", bg=CHARCOAL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.progress = ttk.Progressbar(pc, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=4)
        # actions
        bar = tk.Frame(frame, bg=CHARCOAL)
        bar.pack(fill="x", pady=8)
        for text, action, color in (("Find Proxies", "discover", ACCENT), ("Check Proxies", "check", GREEN),
                                   ("Refresh", "refresh", PURPLE), ("Stop", "stop", RED),
                                   ("Download Proxies", "download_all", ORANGE)):
            b = tk.Button(bar, text=text, bg=color, fg="white", bd=0, padx=14, pady=8,
                          font=("Segoe UI", 10, "bold"), cursor="hand2",
                          command=lambda a=action: self._run(a))
            b.pack(side="left", padx=4)
        self.dash_status = tk.Label(frame, text="Ready", bg=CHARCOAL, fg=MUTED, font=("Segoe UI", 10))
        self.dash_status.pack(anchor="w", pady=4)

    # --------------------------------------------------------------- proxy list
    def _build_proxy_list(self, frame):
        toolbar = tk.Frame(frame, bg=CHARCOAL)
        toolbar.pack(fill="x", pady=6)
        self.search_var = tk.StringVar()
        tk.Entry(toolbar, textvariable=self.search_var, bg=SURFACE, fg=TEXT, insertbackground=TEXT, width=28,
                 bd=0).pack(side="left", padx=4, ipady=6)
        self.country_filter = tk.StringVar(value="All")
        self.proto_filter = tk.StringVar(value="All")
        tk.Label(toolbar, text="Country", bg=CHARCOAL, fg=MUTED).pack(side="left", padx=(12, 4))
        ttk.Combobox(toolbar, textvariable=self.country_filter, values=("All",), width=8, state="readonly").pack(side="left")
        tk.Label(toolbar, text="Protocol", bg=CHARCOAL, fg=MUTED).pack(side="left", padx=(12, 4))
        ttk.Combobox(toolbar, textvariable=self.proto_filter, values=("All", "http", "https", "socks4", "socks5"),
                     width=10, state="readonly").pack(side="left")
        for text, action in (("Copy", "copy_selected"), ("Download Selected", "export_selected"),
                             ("Download All", "export_all_working")):
            tk.Button(toolbar, text=text, bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                      command=lambda a=action: self._run(a)).pack(side="left", padx=4)
        self.worker_var = tk.StringVar(value="50")
        tk.Label(toolbar, text="Workers", bg=CHARCOAL, fg=MUTED).pack(side="left", padx=(12, 4))
        ttk.Combobox(toolbar, textvariable=self.worker_var, values=("10", "50", "100", "200", "500"),
                     width=6, state="readonly").pack(side="left")
        self.limit_var = tk.StringVar(value="500")
        tk.Entry(toolbar, textvariable=self.limit_var, bg=SURFACE, fg=TEXT, width=8, bd=0).pack(side="left", padx=(8, 4), ipady=6)
        tk.Label(toolbar, text="max", bg=CHARCOAL, fg=MUTED).pack(side="left")
        for text, action in (("Find", "discover"), ("Check", "check"), ("Discover+Check", "refresh"), ("Stop", "stop")):
            tk.Button(toolbar, text=text, bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                      command=lambda a=action: self._run(a)).pack(side="left", padx=4)

        card = tk.Frame(frame, bg=SURFACE)
        card.pack(fill="both", expand=True, pady=6)
        cols = ("ip", "port", "protocol", "country", "latency", "status", "checked")
        self.table = ttk.Treeview(card, columns=cols, show="headings", selectmode="extended")
        for c, label, w in zip(cols, ("IP Address", "Port", "Protocol", "Country", "Latency (ms)", "Health", "Last Checked"), (150, 70, 90, 110, 100, 90, 150)):
            self.table.heading(c, text=label, command=lambda col=c: self._sort(col))
            self.table.column(c, width=w, minwidth=60)
        vsb = ttk.Scrollbar(card, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=vsb.set)
        self.table.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.table.tag_configure("healthy", foreground=GREEN)
        self.table.tag_configure("slow", foreground=ORANGE)
        self.table.tag_configure("dead", foreground=RED)

    # --------------------------------------------------------------- gateway
    def _build_gateway(self, frame):
        card = self._card(frame, "Rotating Gateway")
        self.gw_labels = {}
        for key in ("status", "endpoint", "country", "mode", "healthy", "unique_ips", "active", "success", "failed", "current_ip", "latency"):
            row = tk.Frame(card, bg=SURFACE)
            row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=key.replace("_", " ").title(), bg=SURFACE, fg=MUTED, width=18, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="-", bg=SURFACE, fg=TEXT)
            lbl.pack(side="left")
            self.gw_labels[key] = lbl
        bar = tk.Frame(frame, bg=CHARCOAL)
        bar.pack(fill="x", pady=8)
        for text, action in (("Start", "gateway_start"), ("Stop", "gateway_stop"), ("Restart", "gateway_restart"),
                             ("Test", "test_connection")):
            tk.Button(bar, text=text, bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                      command=lambda a=action: self._run(a)).pack(side="left", padx=4)
        self.country_var = tk.StringVar(value="all")
        tk.Entry(bar, textvariable=self.country_var, bg=SURFACE, fg=TEXT, width=12, bd=0).pack(side="left", padx=6, ipady=6)
        tk.Button(bar, text="Apply country", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=lambda: self._run("gateway_countries")).pack(side="left", padx=4)
        self.mode_var = tk.StringVar(value="per_connection")
        ttk.Combobox(bar, textvariable=self.mode_var, values=list(self.controller.rotation_modes),
                     width=18, state="readonly").pack(side="left", padx=6)
        tk.Button(bar, text="Set mode", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=lambda: self._run("gateway_mode")).pack(side="left", padx=4)
        auth = self._card(frame, "Authentication (PBKDF2)")
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        tk.Entry(auth, textvariable=self.user_var, bg=SURFACE, fg=TEXT, width=20, bd=0).pack(side="left", padx=6, pady=8, ipady=6)
        tk.Entry(auth, textvariable=self.pass_var, bg=SURFACE, fg=TEXT, width=20, show="*", bd=0).pack(side="left", padx=6, ipady=6)
        tk.Button(auth, text="Save credentials", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=lambda: self._run("gateway_auth")).pack(side="left", padx=6)

    # --------------------------------------------------------------- downloads
    def _build_downloads(self, frame):
        card = self._card(frame, "Export & Download History")
        top = tk.Frame(card, bg=SURFACE)
        top.pack(fill="x", padx=14, pady=6)
        self.export_dir_var = tk.StringVar(value=str(self.export_dir))
        tk.Entry(top, textvariable=self.export_dir_var, bg=SURFACE2, fg=TEXT, bd=0, width=50).pack(side="left", ipady=6)
        tk.Button(top, text="Choose folder", bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                  command=self._choose_folder).pack(side="left", padx=6)
        tk.Button(top, text="Open folder", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=self._open_folder).pack(side="left", padx=6)
        self.auto_export_var = tk.BooleanVar(value=bool(self.controller.config.get("auto_export", False)))
        tk.Checkbutton(top, text="Auto-export after check", variable=self.auto_export_var, bg=SURFACE, fg=TEXT,
                       selectcolor=SURFACE2, command=self._save_auto_export).pack(side="left", padx=10)
        fmts = tk.Frame(card, bg=SURFACE)
        fmts.pack(fill="x", padx=14, pady=6)
        tk.Label(fmts, text="Format:", bg=SURFACE, fg=MUTED).pack(side="left")
        self.export_format_var = tk.StringVar(value="json")
        for f in ("json", "txt", "csv"):
            tk.Radiobutton(fmts, text=f.upper(), variable=self.export_format_var, value=f, bg=SURFACE, fg=TEXT,
                           selectcolor=SURFACE2).pack(side="left", padx=6)
        tk.Label(fmts, text="Scope:", bg=SURFACE, fg=MUTED).pack(side="left", padx=(12, 4))
        self.export_scope_var = tk.StringVar(value="all")
        ttk.Combobox(fmts, textvariable=self.export_scope_var,
                     values=("all", "selected", "country", "http", "https", "socks4", "socks5"),
                     width=12, state="readonly").pack(side="left")
        tk.Button(fmts, text="Download (Save As)", bg=GREEN, fg="white", bd=0, padx=12, pady=6,
                  command=lambda: self._run("export_saveas")).pack(side="left", padx=8)
        tk.Button(fmts, text="Quick export", bg=ACCENT, fg="white", bd=0, padx=12, pady=6,
                  command=lambda: self._run("export_quick")).pack(side="left", padx=4)

        self.history_tree = ttk.Treeview(card, columns=("name", "format", "count", "size", "time"), show="headings", height=14)
        for col, label, w in zip(("name", "format", "count", "size", "time"),
                                 ("File", "Format", "Count", "Size", "Date"), (260, 80, 70, 90, 170)):
            self.history_tree.heading(col, text=label)
            self.history_tree.column(col, width=w, minwidth=60)
        self.history_tree.pack(fill="both", expand=True, padx=14, pady=6)
        hb = tk.Frame(card, bg=SURFACE)
        hb.pack(fill="x", padx=14, pady=6)
        for text, action in (("Open file", "open_export"), ("Open folder", "open_export_folder"),
                             ("Delete entry", "delete_export")):
            tk.Button(hb, text=text, bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                      command=lambda a=action: self._run(a)).pack(side="left", padx=4)
        self._update_history()

    # --------------------------------------------------------------- settings
    def _build_settings(self, frame):
        card = self._card(frame, "Settings")
        self.timeout_var = tk.StringVar(value=str(self.controller.config["timeout_seconds"]))
        tk.Label(card, text="Timeout (s)", bg=SURFACE, fg=MUTED).pack(anchor="w", padx=14)
        tk.Entry(card, textvariable=self.timeout_var, bg=SURFACE2, fg=TEXT, width=8, bd=0).pack(anchor="w", padx=14, pady=4, ipady=6)
        tk.Button(card, text="Save", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=self._save_settings).pack(anchor="w", padx=14, pady=6)
        tk.Button(card, text="Change Backend Connection", bg=SURFACE2, fg=TEXT, bd=0,
                  padx=10, pady=6, command=self._change_connection).pack(anchor="w", padx=14, pady=4)
        self.auto_update_var = tk.BooleanVar(value=bool(self.controller.config.get("auto_update", True)))
        tk.Checkbutton(card, text="Enable automatic updates", variable=self.auto_update_var, bg=SURFACE, fg=TEXT,
                       selectcolor=SURFACE2, command=self._save_auto_update).pack(anchor="w", padx=14, pady=4)
        self.update_status = tk.Label(card, text=f"Current version: 4.0.0", bg=SURFACE, fg=MUTED)
        self.update_status.pack(anchor="w", padx=14, pady=4)
        tk.Button(card, text="Check for Updates", bg=ACCENT, fg="white", bd=0, padx=10, pady=6,
                  command=self._check_updates_now).pack(anchor="w", padx=14, pady=4)
        self.update_button = tk.Button(
            card, text="Restart and Update", bg=GREEN, fg="white", bd=0,
            padx=10, pady=6, state="disabled", command=self._restart_and_update,
        )
        self.update_button.pack(anchor="w", padx=14, pady=4)
        self.update_progress = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.update_progress.pack(fill="x", padx=14, pady=4)
        # advanced diagnostics
        diag = self._card(frame, "Advanced Diagnostics")
        self.diag_text = tk.Text(diag, bg=SURFACE2, fg=TEXT, height=12, bd=0)
        self.diag_text.pack(fill="both", expand=True, padx=14, pady=8)
        tk.Button(diag, text="Refresh diagnostics", bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                  command=self._refresh_diag).pack(anchor="w", padx=14, pady=6)
        tk.Button(diag, text="Copy gateway endpoint", bg=SURFACE2, fg=TEXT, bd=0, padx=10, pady=6,
                  command=lambda: self._run("copy_endpoint")).pack(anchor="w", padx=14, pady=4)
        tk.Label(frame, text="Free public proxies are untrusted — never send sensitive data.",
                 bg=CHARCOAL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=10)

    def _build_about(self, frame):
        card = self._card(frame, "About")
        for line in (
            "ProxyHunter v4.0.0 — Windows Desktop Edition",
            "Modern UI, server-side discovery/validation, verified updates.",
            "The rotating gateway is managed by your configured backend.",
            "No browser engine bundled. Lightweight Tkinter UI.",
        ):
            tk.Label(card, text=line, bg=SURFACE, fg=TEXT).pack(anchor="w", padx=14, pady=2)

    # ---------------------------------------------------------------- actions
    def _bind_keys(self):
        self.bind("<Control-c>", lambda e: self._run("copy_selected"))

    def _on_nav(self, _event=None):
        sel = self.nav.curselection()
        if not sel:
            return
        name = self.nav.get(sel[0]).strip()
        if name in self.frames:
            self._show(name)

    def _show(self, name):
        self.header.config(text=name)
        for key, frame in self.frames.items():
            frame.tkraise() if key == name else None

    def _run(self, action, value=""):
        c = self.controller
        if action == "discover":
            if hasattr(self, "worker_var"):
                c.config["workers"]["count"] = max(1, min(500, int(self.worker_var.get() or 50)))
            coro = c.discover()
        elif action == "check":
            coro = c.check(limit=int(self.limit_var.get() or 0)) if hasattr(self, "limit_var") else c.check()
        elif action == "refresh":
            coro = c.discover_and_check(limit=int(self.limit_var.get() or 500))
        elif action == "stop":
            c.request_stop()
            return
        elif action == "download_all":
            self._export_saveas(scope="all")
            return
        elif action == "export_all_working":
            self._export_saveas(scope="all")
            return
        elif action == "export_selected":
            self._export_saveas(scope="selected")
            return
        elif action == "export_saveas":
            self._export_saveas(scope=self.export_scope_var.get())
            return
        elif action == "export_quick":
            self._export_quick(self.export_scope_var.get())
            return
        elif action == "copy_selected":
            if hasattr(self, "table"):
                lines = [self.table.item(i, "values")[0] for i in self.table.selection()]
                self.clipboard_clear()
                self.clipboard_append("\n".join(lines))
            return
        elif action == "gateway_start":
            coro = c.gateway_start()
        elif action == "gateway_stop":
            coro = c.gateway_stop()
        elif action == "gateway_restart":
            coro = c.gateway_restart()
        elif action == "gateway_countries":
            c.gateway_select_countries(self.country_var.get())
            return
        elif action == "gateway_mode":
            c.gateway_set_mode(self.mode_var.get())
            return
        elif action == "gateway_auth":
            c.gateway_set_credentials(self.user_var.get(), self.pass_var.get())
            messagebox.showinfo("ProxyHunter", "Credentials saved as PBKDF2 hash.")
            return
        elif action == "copy_endpoint":
            self.clipboard_clear()
            self.clipboard_append(c.gateway.snapshot()["endpoint"])
            return
        elif action == "test_connection":
            messagebox.showinfo("ProxyHunter", "Run an authorized IP-check endpoint through the gateway to verify.")
            return
        elif action == "open_export":
            self._open_selected_export()
            return
        elif action == "open_export_folder":
            self._open_folder()
            return
        elif action == "delete_export":
            self._delete_selected_export()
            return
        else:
            return
        self.pending.append(self.worker.submit(coro))

    # --------------------------------------------------------------- export logic
    def _selected_proxies(self):
        if not hasattr(self, "table"):
            return []
        selected = self.table.selection()
        ips = {self.table.item(i, "values")[0] for i in selected}
        return [p for p in self.controller.proxies() if p.get("host") in ips]

    def _scope_proxies(self, scope):
        c = self.controller
        allp = c.proxies()
        if scope == "all":
            return allp
        if scope == "selected":
            return self._selected_proxies() or allp
        if scope == "country":
            # use country filter combobox if present
            return allp
        if scope in ("http", "https", "socks4", "socks5"):
            return [p for p in allp if p.get("protocol") == scope]
        return allp

    def _export_saveas(self, scope="all"):
        proxies = self._scope_proxies(scope)
        if not proxies:
            messagebox.showwarning("Export", "No proxies to export.")
            return
        fmt = self.export_format_var.get()
        default_name = suggested_name("all" if scope == "all" else scope, "")
        path = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}",
            filetypes=[(f"{fmt.upper()} files", f"*.{fmt}"), ("All files", "*.*")],
            initialfile=f"{default_name}.{fmt}",
            initialdir=str(self.export_dir),
            title="Save exported proxies",
        )
        if not path:
            return
        try:
            items = [Proxy.from_dict(d) for d in proxies]
            created = export_proxies(items, Path(path).parent, Path(path).stem, formats=(fmt,), address_format="ip_port")
            # rename to exact chosen filename if needed
            created_path = Path(created[0]["path"])
            chosen = Path(path)
            if created_path != chosen:
                if chosen.exists():
                    chosen.unlink()
                created_path.replace(chosen)
            count = len(items)
            messagebox.showinfo("Download complete", f"Saved {count} proxies to:\n{chosen}")
            self._update_history()
            if hasattr(self, "diag_text"):
                self.diag_text.insert("end", f"Exported {count} to {chosen}\n")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export failed", str(exc))

    def _export_quick(self, scope):
        fmt = self.export_format_var.get()
        name = suggested_name("all" if scope == "all" else scope, "")
        try:
            # Export on the backend and download the generated file(s).
            created = self.controller.export(str(self.export_dir), name, formats=(fmt,))
            if not created:
                messagebox.showwarning("Export", "No proxies to export or backend unavailable.")
                return
            messagebox.showinfo("Download complete", f"{len(created)} file(s) in {self.export_dir}")
            self._update_history()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export failed", str(exc))

    def _open_folder(self):
        try:
            os.startfile(str(self.export_dir))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open folder", str(exc))

    def _open_selected_export(self):
        sel = self.history_tree.selection() if hasattr(self, "history_tree") else ()
        if not sel:
            return
        vals = self.history_tree.item(sel[0], "values")
        name = vals[0]
        path = Path(self.export_dir) / name
        try:
            os.startfile(str(path))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open file", str(exc))

    def _delete_selected_export(self):
        sel = self.history_tree.selection() if hasattr(self, "history_tree") else ()
        if not sel:
            return
        vals = self.history_tree.item(sel[0], "values")
        entry = {"path": str(Path(self.export_dir) / vals[0]), "name": vals[0]}
        if delete_export(entry):
            self._update_history()

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=str(self.export_dir))
        if folder:
            self.export_dir = Path(folder)
            self.export_dir_var.set(str(self.export_dir))
            self._update_history()

    def _update_history(self):
        if not hasattr(self, "history_tree"):
            return
        for row in list(self.history_tree.get_children("")):
            self.history_tree.delete(row)
        for item in export_history(self.export_dir, 50):
            self.history_tree.insert("", "end", values=(
                item.get("name", ""), item.get("format", ""),
                item.get("count", 0), item.get("size_bytes", 0), item.get("timestamp", ""),
            ))

    def _change_connection(self):
        import tkinter.simpledialog as sd
        current = load_connection()
        url = sd.askstring("Backend connection", "Backend HTTPS URL:",
                           initialvalue=current.get("url", "https://"))
        if not url:
            return
        key = sd.askstring("Backend connection", "API key:", show="*",
                           initialvalue=current.get("api_key", ""))
        if key is None:
            return
        save_connection(url, key)
        self.controller.base_url = url.rstrip("/")
        self.controller.api_key = key
        messagebox.showinfo("ProxyHunter", "Connection saved. Restart the app to reconnect.")

    def _save_settings(self):
        try:
            self.controller.config["timeout_seconds"] = max(1.0, float(self.timeout_var.get()))
            from proxyhunter.config import save_config
            save_config(self.controller.config)
            messagebox.showinfo("ProxyHunter", "Settings saved.")
        except ValueError:
            messagebox.showerror("ProxyHunter", "Enter a numeric timeout.")

    def _save_auto_update(self):
        self.controller.config["auto_update"] = bool(self.auto_update_var.get())
        try:
            from proxyhunter.config import save_config
            save_config(self.controller.config)
        except Exception:  # noqa: BLE001
            pass

    def _save_auto_export(self):
        self.controller.config["auto_export"] = bool(self.auto_export_var.get())
        try:
            from proxyhunter.config import save_config
            save_config(self.controller.config)
        except Exception:  # noqa: BLE001
            pass

    def _refresh_diag(self):
        if not hasattr(self, "diag_text"):
            return
        s = self.controller.stats()
        self.diag_text.delete("1.0", "end")
        for k in ("backend", "gateway", "internet", "endpoint", "operation", "progress",
                  "discovered", "checked", "working", "dead", "active_workers",
                  "configured_workers", "avg_latency", "cpu", "ram", "sources_enabled"):
            self.diag_text.insert("end", f"{k}: {s.get(k)}\n")

    def _check_updates_now(self):
        if self._pending_update:
            self.update_status.config(text="Update ready. Click Restart and Update.")
            self.update_button.config(state="normal")
            return
        self.update_status.config(text="Checking for updates...")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            from proxyhunter.updater import check_for_update, download_update
            info = check_for_update()
            if info.get("error"):
                self.after(0, lambda: self.update_status.config(text=f"Update check failed: {info['error']}"))
                return
            if not info.get("available"):
                self.after(0, lambda: self.update_status.config(text=f"Up to date (latest {info.get('version')})"))
                return
            self.after(0, lambda: self.update_status.config(text=f"Update available: {info['version']} — downloading..."))
            dest = Path(os.environ.get("TEMP", ".")) / f"ProxyHunter_v{info['version']}_Windows.exe"
            def progress(done, total, speed=0, eta=0):
                if total:
                    self.after(0, lambda d=done, t=total: self.update_progress.config(value=d / t * 100))
                mb = done / (1024 * 1024)
                spd = speed / (1024 * 1024)
                self.after(0, lambda m=mb, s=spd, e=eta: self.update_status.config(
                    text=f"Downloading {info['version']}: {m:.1f} MB ({s:.2f} MB/s, ETA {int(e)}s)"))
            download_update(info["url"], info.get("sha256", ""), dest, progress=progress)
            self._pending_update = dest
            self._pending_update_version = str(info.get("version", ""))
            self.after(0, lambda: self.update_status.config(
                text=f"Update {info['version']} verified. Click Restart and Update."))
            self.after(0, lambda: self.update_button.config(state="normal"))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self.update_status.config(text=f"Update error: {exc}"))

    def _restart_and_update(self):
        if not self._pending_update:
            messagebox.showinfo("ProxyHunter", "No verified update is ready yet.")
            return
        try:
            from proxyhunter.updater import schedule_install
            schedule_install(Path(sys.executable), self._pending_update,
                             expected_version=self._pending_update_version)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Update", f"Could not start the updater: {exc}")
            return
        # Close gracefully; the helper waits for this PID to exit, replaces the
        # EXE, relaunches it and rolls back if the new build does not start.
        self.on_close()

    def _auto_update_loop(self):
        time.sleep(30)
        while True:
            try:
                self._check_updates_now()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(6 * 3600)

    # ---------------------------------------------------------------- poll
    def _poll(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                pass
        self.pending = [f for f in self.pending if not f.done()]
        # source test future handling (kept simple)
        self._update_stats()
        self._update_table()
        self._update_history()
        self.after(250, self._poll)

    def _update_stats(self):
        try:
            s = self.controller.stats()
        except Exception:  # noqa: BLE001
            return
        for key, label in getattr(self, "stat_cards", {}).items():
            if key == "countries_count":
                val = s.get("countries")
                if isinstance(val, dict):
                    val = len(val)
                elif val is None:
                    val = 0
            elif key == "avg_latency":
                val = round(s.get("avg_latency", 0), 1)
            else:
                val = s.get(key, 0)
            label.config(text="n/a" if val is None else str(val))
        if hasattr(self, "progress"):
            self.progress["value"] = float(s.get("progress", 0)) * 100
        # auto-export
        if (self.controller.config.get("auto_export") and s.get("operation") == "idle"
                and s.get("checked", 0) > 0 and not getattr(self, "_auto_exported", False)):
            self._auto_exported = True
            try:
                self._export_quick("all")
            except Exception:  # noqa: BLE001
                pass
        if s.get("operation") != "idle":
            self._auto_exported = False
        # gateway labels (internal endpoint stays in Advanced Diagnostics)
        for key, label in getattr(self, "gw_labels", {}).items():
            if key == "endpoint":
                label.config(text="Hidden (Advanced Diagnostics)")
            else:
                label.config(text=str(s.get(key, "-")))
        # status dot
        if hasattr(self, "status_dot"):
            gw = s.get("gateway", "-")
            self.status_dot.config(text=f"● {gw}", fg=GREEN if gw == "ONLINE" else RED)

    def _update_table(self):
        if not hasattr(self, "table"):
            return
        query = self.search_var.get().lower() if hasattr(self, "search_var") else ""
        cf = self.country_filter.get() if hasattr(self, "country_filter") else "All"
        pf = self.proto_filter.get() if hasattr(self, "proto_filter") else "All"
        current = set(self.table.get_children(""))
        for row in list(current):
            self.table.delete(row)
        for p in self.controller.proxies():
            if query and query not in str(p).lower():
                continue
            if cf not in ("All", "") and p.get("country_code") != cf:
                continue
            if pf not in ("All", "") and p.get("protocol") != pf:
                continue
            latency = p.get("response_time_ms", 0) or 0
            if p.get("working"):
                tag = "slow" if latency and latency > 2000 else "healthy"
                status = "HEALTHY"
            else:
                tag = "dead"
                status = "DEAD"
            flag = COUNTRY_FLAGS.get(str(p.get("country_code", "")).upper(), "🌐")
            self.table.insert("", "end", values=(
                p["host"], p["port"], p["protocol"],
                f"{flag} {p.get('country_code', '')}", round(latency),
                status, p.get("last_checked", ""),
            ), tags=(tag,))

    def _sort(self, column):
        if not hasattr(self, "table"):
            return
        items = list(self.table.get_children(""))
        idx = ("ip", "port", "protocol", "country", "latency", "status", "checked").index(column)
        items.sort(key=lambda i: str(self.table.item(i, "values")[idx]))
        for pos, item in enumerate(items):
            self.table.move(item, "", pos)

    def _context_menu(self, event):
        pass

    def _open_folder(self):
        try:
            os.startfile(str(self.export_dir))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open folder", str(exc))

    def on_close(self):
        try:
            for future in self.pending:
                future.cancel()
            self.worker.shutdown()
            self.controller.close()
        finally:
            self.destroy()

def main():
    # Fallback for unusual launchers that import this module instead of running
    # it as __main__.  The early dispatch above is the normal path.
    if _selftest_requested():
        from selftest_mode import run_selftest

        raise SystemExit(run_selftest())
    # Single-instance guard (Wine/Winlator safe).  Never use os.kill(pid, 0)
    # on Windows: it raises OSError/WinError 6 and SystemError under Wine.
    import socket
    _single = None
    try:
        _single = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _single.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _single.bind(("127.0.0.1", 47831))
        _single.listen(1)
    except OSError:
        # Another instance is already running (or the port is unavailable).
        try:
            if _single is not None:
                _single.close()
        except OSError:
            pass
        return
    app = ProxyHunterApp()
    # Keep the socket alive for the process lifetime.
    app._single_instance_socket = _single
    if "--startup" in sys.argv:
        app.after(300, app.iconify)
    try:
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new("RGBA", (64, 64), (11, 18, 32, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((14, 14, 50, 50), outline=(16, 185, 129, 255), width=5)
        icon = pystray.Icon("ProxyHunter", image, "ProxyHunter v4.0.0")
        threading.Thread(target=icon.run, daemon=True).start()
    except ImportError:
        pass
    app.mainloop()


if __name__ == "__main__":
    raise SystemExit(main())