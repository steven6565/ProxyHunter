#!/usr/bin/env python3
"""ProxyHunter v3.0 Windows desktop application (Tkinter, no browser engine)."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))

from backend.controller import BackendController, BackendWorker  # noqa: E402
from shared.exports import default_export_dir, export_history, suggested_name  # noqa: E402

NAVY = "#0B1220"
CHARCOAL = "#11161F"
SURFACE = "#182130"
EMERALD = "#10B981"
RED = "#EF4444"
MUTED = "#94A3B8"
TEXT = "#E6EDF3"

SECTIONS = [
    "Dashboard", "Proxy Discovery", "Proxy Checker", "Proxy List",
    "Rotating Gateway", "Downloads", "Activity Logs", "Settings", "About",
]


class ProxyHunterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProxyHunter v3.0 — Desktop Edition")
        self.geometry("1180x760")
        self.minsize(940, 620)
        self.configure(bg=CHARCOAL)
        self.events: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.controller = BackendController(on_event=lambda kind, data: self.events.put((kind, data)))
        self.worker = BackendWorker(self.controller)
        self.pending: list = []
        if self.controller.config.get("gateway", {}).get("auto_start", True):
            self.pending.append(self.worker.submit(self.controller.gateway_start()))
        self.dark = True
        self.export_dir = default_export_dir(desktop=True)
        self._styles()
        self._layout()
        self._bind_keys()
        self.after(200, self._poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------------------------------------------------------- styling
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
        style.configure("Title.TLabel", background=CHARCOAL, foreground=TEXT, font=("Segoe UI", 16, "bold"))
        style.configure("Good.TLabel", background=CHARCOAL, foreground=EMERALD, font=("Segoe UI", 10, "bold"))
        style.configure("Bad.TLabel", background=CHARCOAL, foreground=RED, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=SURFACE, foreground=TEXT, borderwidth=0, padding=8)
        style.map("TButton", background=[("active", "#233348")])
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT)
        style.configure("Treeview", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
                        rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=SURFACE, foreground=TEXT)
        style.configure("TProgressbar", background=EMERALD, troughcolor=NAVY)

    # ------------------------------------------------------------------- layout
    def _layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        side = ttk.Frame(self, style="Side.TFrame", width=190)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        ttk.Label(side, text="◈  ProxyHunter", style="Title.TLabel").pack(pady=(20, 16))
        self.nav = ttk.Treeview(side, show="tree", height=12)
        self.nav.pack(fill="both", padx=8)
        for section in SECTIONS:
            self.nav.insert("", "end", text="  " + section, tags=(section,))
        self.nav.selection_set(self.nav.get_children()[0])
        self.nav.bind("<<TreeviewSelect>>", self._on_nav)
        ttk.Label(side, text="v3.0 · local gateway", style="Muted.TLabel").pack(side="bottom", pady=14)

        self.content = ttk.Frame(self, padding=18)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)
        self.header = ttk.Label(self.content, text="Dashboard", style="Title.TLabel")
        self.header.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.body = ttk.Frame(self.content)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.frames = {
            name: self._build_section(name) for name in SECTIONS
        }
        for frame in self.frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
        self._show("Dashboard")

    def _card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.pack(fill="x", pady=6)
        ttk.Label(card, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        return card

    def _build_section(self, name: str) -> ttk.Frame:
        frame = ttk.Frame(self.body)
        if name == "Dashboard":
            self.stat_labels = {}
            card = self._card(frame, "Live status")
            for key in ("status", "backend", "internet", "gateway", "endpoint", "country", "mode", "discovered", "working",
                        "unique_ips", "healthy", "checked", "speed", "active", "workers",
                        "latency", "uptime", "last_refresh", "cpu", "ram"):
                row = ttk.Frame(card, style="Card.TFrame")
                row.pack(fill="x")
                ttk.Label(row, text=key.replace("_", " ").title(), style="Muted.TLabel").pack(side="left", width=22)
                lbl = ttk.Label(row, text="-", style="Card.TLabel")
                lbl.pack(side="left")
                self.stat_labels[key] = lbl
            ops = self._card(frame, "Controls")
            bar = ttk.Frame(ops, style="Card.TFrame")
            bar.pack(fill="x")
            for text, action in (("Find Proxies", "discover"), ("Check Proxies", "check"),
                                 ("Refresh", "refresh"), ("Stop", "stop")):
                ttk.Button(bar, text=text, command=lambda a=action: self._run(a)).pack(side="left", padx=4)
            self.progress = ttk.Progressbar(ops, mode="determinate", maximum=100)
            self.progress.pack(fill="x", pady=8)
        elif name in ("Proxy Discovery", "Proxy Checker"):
            card = self._card(frame, name)
            ttk.Label(card, text="Bounded async workers · rate limits always respected",
                      style="Muted.TLabel").pack(anchor="w")
            for text, action in (("Discover", "discover"), ("Check all", "check"),
                                 ("Discover + check", "refresh"), ("Stop", "stop")):
                ttk.Button(card, text=text, command=lambda a=action: self._run(a)).pack(side="left", padx=4, pady=10)
            self.limit_var = tk.StringVar(value="500")
            ttk.Entry(card, textvariable=self.limit_var, width=10).pack(side="left", padx=6)
            ttk.Label(card, text="max proxies", style="Muted.TLabel").pack(side="left")
        elif name == "Proxy List":
            self._build_table(frame)
        elif name == "Rotating Gateway":
            self._build_gateway(frame)
        elif name == "Downloads":
            self._build_downloads(frame)
        elif name == "Activity Logs":
            self.log_text = tk.Text(frame, bg=SURFACE, fg=TEXT, insertbackground=TEXT, height=24)
            self.log_text.pack(fill="both", expand=True)
        elif name == "Settings":
            card = self._card(frame, "Settings")
            ttk.Button(card, text="Toggle dark / light theme", command=self._toggle_theme).pack(anchor="w")
            self.timeout_var = tk.StringVar(value=str(self.controller.config["timeout_seconds"]))
            ttk.Entry(card, textvariable=self.timeout_var, width=8).pack(side="left", padx=6)
            ttk.Label(card, text="Timeout (s)", style="Muted.TLabel").pack(side="left")
            ttk.Button(card, text="Save", command=self._save_settings).pack(side="left", padx=8)
            ttk.Label(card, text="Free public proxies are untrusted — never send sensitive data.",
                      style="Muted.TLabel").pack(anchor="w", pady=10)
        else:
            card = self._card(frame, "About")
            for line in (
                "ProxyHunter v3.0 — Desktop & Mobile Edition",
                "Preserved v2/v3 async backend, six rotation modes, country filters.",
                "Gateway: http://127.0.0.1:8080 (localhost by default).",
                "No browser engine bundled. Lightweight Tkinter UI.",
            ):
                ttk.Label(card, text=line, style="Card.TLabel").pack(anchor="w")
        return frame

    def _build_table(self, frame: ttk.Frame) -> None:
        card = ttk.Frame(frame, style="Card.TFrame")
        card.pack(fill="both", expand=True)
        columns = ("ip", "port", "protocol", "country", "latency", "status", "checked")
        self.table = ttk.Treeview(card, columns=columns, show="headings", selectmode="extended")
        for col, label in zip(columns, ("IP Address", "Port", "Protocol", "Country", "Latency", "Status", "Last Checked")):
            self.table.heading(col, text=label, command=lambda c=col: self._sort(c))
            self.table.column(col, width=140 if col == "ip" else 110)
        scroll = ttk.Scrollbar(card, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<Button-3>", self._context_menu)
        toolbar = ttk.Frame(frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=6)
        self.search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search_var, width=30).pack(side="left", padx=4)
        for text, action in (("Copy", "copy_selected"), ("Export CSV", "export_csv"),
                             ("Refresh", "refresh_list")):
            ttk.Button(toolbar, text=text, command=lambda a=action: self._run(a)).pack(side="left", padx=4)

    def _build_gateway(self, frame: ttk.Frame) -> None:
        card = self._card(frame, "Rotating gateway")
        self.gw_labels = {}
        for key in ("status", "endpoint", "country", "mode", "healthy", "unique_ips",
                    "active", "success", "failed", "current_ip", "latency"):
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x")
            ttk.Label(row, text=key.replace("_", " ").title(), style="Muted.TLabel").pack(side="left", width=18)
            lbl = ttk.Label(row, text="-", style="Card.TLabel")
            lbl.pack(side="left")
            self.gw_labels[key] = lbl
        bar = ttk.Frame(card, style="Card.TFrame")
        bar.pack(fill="x", pady=8)
        for text, action in (("Start", "gateway_start"), ("Stop", "gateway_stop"),
                             ("Restart", "gateway_restart"), ("Copy endpoint", "copy_endpoint"),
                             ("Test", "test_connection")):
            ttk.Button(bar, text=text, command=lambda a=action: self._run(a)).pack(side="left", padx=3)
        self.country_var = tk.StringVar(value="all")
        ttk.Entry(bar, textvariable=self.country_var, width=12).pack(side="left", padx=6)
        ttk.Button(bar, text="Apply country", command=lambda: self._run("gateway_countries")).pack(side="left")
        self.mode_var = tk.StringVar(value="per_connection")
        modes = ttk.Combobox(bar, textvariable=self.mode_var, state="readonly", width=18,
                             values=list(self.controller.rotation_modes))
        modes.pack(side="left", padx=6)
        ttk.Button(bar, text="Set mode", command=lambda: self._run("gateway_mode")).pack(side="left")
        auth = self._card(frame, "Authentication (PBKDF2)")
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        ttk.Entry(auth, textvariable=self.user_var, width=20).pack(side="left", padx=4)
        ttk.Entry(auth, textvariable=self.pass_var, width=20, show="*").pack(side="left", padx=4)
        ttk.Button(auth, text="Save credentials", command=lambda: self._run("gateway_auth")).pack(side="left", padx=4)

    def _build_downloads(self, frame: ttk.Frame) -> None:
        card = self._card(frame, "Export validated results")
        ttk.Label(card, text="Default: %USERPROFILE%\\Downloads\\ProxyHunter\\", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(card, textvariable=tk.StringVar(value=str(self.export_dir)), width=60).pack(fill="x", pady=4)
        bar = ttk.Frame(card, style="Card.TFrame")
        bar.pack(fill="x")
        for text, kind in (("All", "all"), ("US", "country:US"), ("IN", "country:IN"),
                           ("SOCKS5", "protocol:socks5"), ("HTTP", "protocol:http")):
            ttk.Button(bar, text=text, command=lambda k=kind: self._run("export", k)).pack(side="left", padx=3)
        ttk.Button(bar, text="Choose folder", command=self._choose_folder).pack(side="left", padx=6)
        self.history_tree = ttk.Treeview(card, columns=("name", "count", "size", "time"),
                                         show="headings", height=12)
        for col in ("name", "count", "size", "time"):
            self.history_tree.heading(col, text=col.title())
        self.history_tree.pack(fill="x", pady=8)

    # ------------------------------------------------------------------ actions
    def _bind_keys(self) -> None:
        self.bind("<Control-c>", lambda e: self._run("copy_selected"))
        self.bind("<Control-e>", lambda e: self._run("export", "all"))

    def _on_nav(self, _event=None) -> None:
        selected = self.nav.selection()
        if not selected:
            return
        name = self.nav.item(selected[0], "text").strip()
        if name in self.frames:
            self._show(name)

    def _show(self, name: str) -> None:
        self.header.config(text=name)
        for key, frame in self.frames.items():
            frame.tkraise() if key == name else None

    def _run(self, action: str, value: str = "") -> None:
        c = self.controller
        if action == "discover":
            coro = c.discover()
        elif action == "check":
            coro = c.check(limit=int(self.limit_var.get() or 0)) if hasattr(self, "limit_var") else c.check()
        elif action == "refresh":
            coro = c.discover_and_check(limit=int(self.limit_var.get() or 500))
        elif action == "stop":
            c.request_stop()
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
        elif action == "copy_selected":
            selected = self.table.selection() if hasattr(self, "table") else ()
            lines = [self.table.item(i, "values")[0] for i in selected]
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
            return
        elif action == "refresh_list":
            self._update_table()
            return
        elif action == "export":
            if ":" in value:
                kind, val = value.split(":", 1)
            else:
                kind, val = value, ""
            name = suggested_name(kind, val)
            proxies = None
            if kind == "country":
                proxies = [p for p in c.proxies() if p.get("country_code") == val]
            elif kind == "protocol":
                proxies = [p for p in c.proxies() if p.get("protocol") == val]
            files = c.export(str(self.export_dir), name,
                             formats=("txt", "csv", "json") if kind == "all" else ("txt",),
                             proxies=proxies)
            messagebox.showinfo("Export complete", f"{len(files)} file(s) in {self.export_dir}")
            self._update_history()
            return
        else:
            return
        self.pending.append(self.worker.submit(coro))

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=str(self.export_dir))
        if folder:
            self.export_dir = Path(folder)
            self._update_history()

    def _toggle_theme(self) -> None:
        self.dark = not self.dark
        bg = CHARCOAL if self.dark else "#F4F7FA"
        fg = TEXT if self.dark else "#0B1220"
        self.configure(bg=bg)
        self._styles()
        self.log_text.config(bg=SURFACE if self.dark else "white",
                             fg=fg, insertbackground=fg)

    def _save_settings(self) -> None:
        try:
            self.controller.config["timeout_seconds"] = max(1.0, float(self.timeout_var.get()))
            from proxyhunter.config import save_config
            save_config(self.controller.config)
            messagebox.showinfo("ProxyHunter", "Settings saved.")
        except ValueError:
            messagebox.showerror("ProxyHunter", "Enter a numeric timeout.")

    def _sort(self, column: str) -> None:
        items = list(self.table.get_children(""))
        index = ("ip", "port", "protocol", "country", "latency", "status", "checked").index(column)
        items.sort(key=lambda i: str(self.table.item(i, "values")[index]))
        for position, item in enumerate(items):
            self.table.move(item, "", position)

    def _context_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Copy IP:PORT", command=lambda: self._run("copy_selected"))
        menu.add_command(label="Export selected CSV", command=lambda: self._run("export", "selected"))
        menu.post(event.x_root, event.y_root)

    # -------------------------------------------------------------------- poll
    def _poll(self) -> None:
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_text.insert("end", data.get("message", "") + "\n")
                self.log_text.see("end")
        self.pending = [f for f in self.pending if not f.done()]
        self._update_stats()
        self._update_table()
        self._update_history()
        self.after(250, self._poll)

    def _update_stats(self) -> None:
        try:
            s = self.controller.stats()
        except Exception:  # noqa: BLE001
            return
        for key, label in getattr(self, "stat_labels", {}).items():
            value = s.get(key)
            label.config(text="n/a" if value is None else str(value))
        if hasattr(self, "progress"):
            self.progress["value"] = float(s.get("progress", 0)) * 100
        for key, label in getattr(self, "gw_labels", {}).items():
            label.config(text=str(s.get(key, "-")))
            label.config(style="Good.TLabel" if key in ("success", "healthy", "status") else "Card.TLabel")

    def _update_table(self) -> None:
        if not hasattr(self, "table"):
            return
        query = self.search_var.get().lower() if hasattr(self, "search_var") else ""
        current = set(self.table.get_children(""))
        for row in list(current):
            self.table.delete(row)
        for p in self.controller.proxies():
            if query and query not in str(p).lower():
                continue
            self.table.insert("", "end", values=(
                p["host"], p["port"], p["protocol"], p.get("country_code", ""),
                round(p.get("response_time_ms", 0)), "HEALTHY" if p.get("working") else "DEAD",
                p.get("last_checked", ""),
            ))

    def _update_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        for row in list(self.history_tree.get_children("")):
            self.history_tree.delete(row)
        for item in export_history(self.export_dir, 40):
            self.history_tree.insert("", "end", values=(
                item.get("name", ""), item.get("count", 0),
                item.get("size_bytes", 0), item.get("timestamp", ""),
            ))

    def on_close(self) -> None:
        try:
            for future in self.pending:
                future.cancel()
            self.worker.shutdown()
            self.controller.close()
        finally:
            self.destroy()


def selftest() -> None:
    """CI smoke test: initialise the backend and write a marker file."""
    from backend.controller import BackendController
    controller = BackendController()
    stats = controller.stats()
    controller.close()
    Path("selftest.json").write_text(json.dumps({
        "ok": True,
        "version": "3.1.1",
        "endpoint": stats.get("endpoint"),
        "status": stats.get("status"),
    }, indent=2), encoding="utf-8")
    print("ProxyHunter v3.0 selftest OK")


def main() -> None:
    if "--selftest" in sys.argv:
        selftest()
        return
    app = ProxyHunterApp()
    if "--startup" in sys.argv:
        # Launched by the optional Windows startup task: begin in tray.
        app.after(300, app.iconify)
    try:
        import pystray  # optional system tray support
        from PIL import Image, ImageDraw
        image = Image.new("RGBA", (64, 64), (11, 18, 32, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((14, 14, 50, 50), outline=(16, 185, 129, 255), width=5)
        icon = pystray.Icon("ProxyHunter", image, "ProxyHunter v3.0")
        threading.Thread(target=icon.run, daemon=True).start()
    except ImportError:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
