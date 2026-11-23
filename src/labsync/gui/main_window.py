"""LabSync desktop window.

Layout: a sidebar (pages, receiving switch, integrations, theme) and a content
area with status cards along the top and the current page below. Pages are
built once and raised when picked; each refreshes only while it is visible.
"""

from __future__ import annotations

import copy
import csv
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import UTC, datetime, timedelta
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import __version__, paths, plugins, updater
from ..config import ConfigManager, new_destination, new_device, validate
from ..devices.catalog import find_profile
from ..engine import Engine
from ..logging_setup import log_feed
from ..storage.db import Database
from ..transport.runner import DeviceStatus
from . import theme
from .common import PAD, local_ts, make_tree, replace_rows
from .dialogs import DestinationDialog, DeviceDialog, ImagingDialog, SettingsDialog
from .tray import Tray
from .viewers import RawMessageWindow, ReportWindow

log = logging.getLogger("labsync.gui")

STATE_LABELS = {
    "stopped": "Stopped", "starting": "Starting", "listening": "Waiting for analyzer", "connecting": "Connecting",
    "connected": "Connected", "error": "Error",
}

PAGES = (
    ("Instruments", "instruments", "Analyzers connected to this computer"),
    ("Imaging", "imaging", "Images received from CT, MRI, X-ray and ultrasound devices"),
    ("Results", "results", "Every result received, and where it went"),
    ("Delivery", "delivery", "Where results are sent"),
    ("Messages", "messages", "Every transmission, exactly as it was on the wire"),
    ("Log", "log", "What LabSync is doing right now"),
)

THEME_CYCLE = {"system": "light", "light": "dark", "dark": "system"}


def apply_theme(root: tk.Tk, mode: str) -> None:
    """Kept for callers of the old helper; see ``theme.apply``."""
    theme.apply(root, mode)


class MainWindow:
    def __init__(self, root: tk.Tk, mgr: ConfigManager, engine: Engine, db: Database):
        self.root = root
        self.mgr = mgr
        self.engine = engine
        self.db = db
        self.cfg = mgr.snapshot()
        self.statuses: dict[str, DeviceStatus] = {}
        self.quitting = False
        self._dirty = {"results": True, "delivery": True, "messages": True, "imaging": True}
        self.pages: dict[str, ttk.Frame] = {}
        self.nav: dict[str, ttk.Button] = {}
        self.current = "Instruments"

        root.title(self.cfg.get("app_name", "LabSync"))
        root.geometry("1320x800")
        root.minsize(1040, 640)
        icon = paths.resource_path("icon.png")
        try:
            self._icon = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, self._icon)
        except tk.TclError:
            self._icon = None
        if sys.platform == "win32":
            try:
                root.iconbitmap(str(paths.resource_path("icon.ico")))
            except tk.TclError:
                pass

        self._build()
        theme.on_change(self._recolor)
        self._recolor()
        self.tray = Tray(str(paths.resource_path("icon.png")), "LabSync", self.show, self.quit)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if sys.platform == "darwin":
            root.createcommand("tk::mac::ReopenApplication", self.show)
            root.createcommand("tk::mac::Quit", self.quit)
        self.refresh_devices()
        self.root.after(250, self._poll_events)
        self.root.after(2000, self._periodic)
        if self.cfg.get("check_updates", True):
            self.root.after(15000, lambda: self.check_updates(silent=True))
        if mgr.migrated_from:
            self.root.after(800, lambda: messagebox.showinfo(
                "Settings migrated",
                "Your LabSync 1.x settings were converted. Your analyzer and external server were carried over; "
                "a backup of the old file was kept next to the new configuration.", parent=self.root))

    # ================================================================== layout
    def _build(self) -> None:
        r = self.root
        r.bind_all("<Control-q>", lambda e: self.quit())
        r.bind_all("<Control-comma>", lambda e: self.edit_settings())
        self._menu = tk.Menu(r, tearoff=False)
        self._menu.add_command(label="Settings…", command=self.edit_settings, accelerator="Ctrl+,")
        self._menu.add_command(label="Imaging settings…", command=self.edit_imaging)
        self._menu.add_separator()
        self._menu.add_command(label="Open data folder", command=lambda: _open_path(paths.app_home()))
        self._menu.add_command(label="Open log folder", command=lambda: _open_path(paths.log_dir()))
        self._menu.add_separator()
        self._menu.add_command(label="Check for updates…", command=lambda: self.check_updates(silent=False))
        self._menu.add_command(label="Documentation",
                               command=lambda: webbrowser.open("https://github.com/harrisyn/LabAnalyzer#readme"))
        self._menu.add_command(label="About LabSync", command=self.about)
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self.quit, accelerator="Ctrl+Q")
        if sys.platform == "darwin":  # macOS keeps its menu bar
            menubar = tk.Menu(r)
            menubar.add_cascade(label="LabSync", menu=self._menu)
            r.config(menu=menubar)

        self._build_sidebar()
        main = ttk.Frame(r, padding=(PAD * 3, PAD * 2.5, PAD * 3, PAD))
        main.pack(side="left", fill="both", expand=True)
        self.main = main

        # Status cards
        kpis = ttk.Frame(main)
        kpis.pack(fill="x", pady=(0, PAD))
        self.kpis: dict[str, ttk.Label] = {}
        self.kpi_cards: dict[str, ttk.Frame] = {}
        for i, (key, title) in enumerate((("connected", "Instruments online"), ("today", "Results today"),
                                          ("pending", "Waiting to send"), ("failed", "Failed deliveries"),
                                          ("images", "Images waiting"))):
            card = ttk.Frame(kpis, style="Card.TFrame", padding=theme.CARD_PAD)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else PAD // 2, 0))
            kpis.columnconfigure(i, weight=1, uniform="kpi")
            self.kpis[key] = ttk.Label(card, text="–", style="CardBig.TLabel")
            self.kpis[key].pack(anchor="w", padx=4)
            ttk.Label(card, text=title, style="CardHint.TLabel").pack(anchor="w", padx=4)
            self.kpi_cards[key] = card

        status = ttk.Frame(main)
        status.pack(fill="x", side="bottom", pady=(PAD // 2, 0))
        self.l_status = ttk.Label(status, text="", style="Hint.TLabel")
        self.l_status.pack(side="left")
        ttk.Label(status, text=f"LabSync {__version__} · {paths.app_home()}", style="Hint.TLabel").pack(side="right")

        self.content = ttk.Frame(main)
        self.content.pack(fill="both", expand=True, pady=(PAD, 0))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self._build_devices()
        self._build_imaging()
        self._build_results()
        self._build_delivery()
        self._build_messages()
        self._build_log()
        self.select_page(self.current)

    def _build_sidebar(self) -> None:
        side = ttk.Frame(self.root, style="Sidebar.TFrame", padding=(PAD * 1.5, PAD * 2.5, PAD * 1.5, PAD * 2))
        side.pack(side="left", fill="y")
        self.sidebar = side
        brand = ttk.Frame(side, style="Sidebar.TFrame")
        brand.pack(fill="x", padx=PAD, pady=(0, PAD * 3))
        self._brand_icon = None
        try:
            from PIL import Image, ImageTk

            img = Image.open(paths.resource_path("icon.png")).convert("RGBA").resize((30, 30), Image.LANCZOS)
            self._brand_icon = ImageTk.PhotoImage(img)
            ttk.Label(brand, image=self._brand_icon, style="Sidebar.TLabel").pack(side="left", padx=(0, PAD))
        except Exception:
            pass
        names = ttk.Frame(brand, style="Sidebar.TFrame")
        names.pack(side="left")
        ttk.Label(names, text=self.cfg.get("app_name", "LabSync"), style="Brand.TLabel").pack(anchor="w")
        self.l_instance = ttk.Label(names, text=self.cfg.get("instance_id", ""), style="SidebarHint.TLabel")
        self.l_instance.pack(anchor="w")

        for title, icon_name, _ in PAGES:
            b = ttk.Button(side, text=f"  {title}", style="Nav.TButton", compound="left", width=20,
                           command=lambda t=title: self.select_page(t), takefocus=False)
            b.pack(fill="x", pady=1)
            b._icon_name = icon_name  # type: ignore[attr-defined]
            self.nav[title] = b

        foot = ttk.Frame(side, style="Sidebar.TFrame")
        foot.pack(side="bottom", fill="x")
        self.side_links = ttk.Frame(foot, style="Sidebar.TFrame")
        self.side_links.pack(fill="x", pady=(0, PAD))
        self.l_receiving = ttk.Label(foot, text="", style="PillNeutral.TLabel")
        self.l_receiving.pack(anchor="w", pady=(0, PAD))
        self.b_engine = ttk.Button(foot, text="Stop receiving", command=self.toggle_engine)
        self.b_engine.pack(fill="x", pady=(0, PAD))
        row = ttk.Frame(foot, style="Sidebar.TFrame")
        row.pack(fill="x")
        self.b_settings = ttk.Button(row, text="  Settings", style="Nav.TButton", compound="left",
                                     command=self.edit_settings, takefocus=False)
        self.b_settings.pack(side="left", fill="x", expand=True)
        self.b_theme = ttk.Button(row, style="Nav.TButton", command=self.cycle_theme, takefocus=False, width=0)
        self.b_theme.pack(side="left", padx=(2, 0))
        self.b_more = ttk.Button(row, style="Nav.TButton", takefocus=False, width=0,
                                 command=lambda: self._menu.tk_popup(self.b_more.winfo_rootx(),
                                                                     self.b_more.winfo_rooty() - 10))
        self.b_more.pack(side="left", padx=(2, 0))

    def _recolor(self) -> None:
        """Things that aren't ttk styles: icons, tag colours, text widgets."""
        for b in self.nav.values():
            name = b._icon_name  # type: ignore[attr-defined]
            b.configure(image=(theme.icon(name, 18, "muted"), "selected", theme.icon(name, 18, "accent")))
        self.b_settings.configure(image=theme.icon("settings", 18, "muted"))
        self.b_theme.configure(image=theme.icon("moon" if theme.mode() == "dark" else "sun", 18, "muted"))
        self.b_more.configure(image=theme.icon("more", 18, "muted"))
        c = theme.color
        for tree in (self.t_dev, self.t_img, self.t_res, self.t_dst, self.t_fail, self.t_msg):
            tree.tag_configure("connected", foreground=c("ok"))
            tree.tag_configure("error", foreground=c("danger"))
            tree.tag_configure("problem", foreground=c("danger"))
            tree.tag_configure("failed", foreground=c("danger"))
            tree.tag_configure("abnormal", foreground=c("danger"))
            tree.tag_configure("waiting", foreground=c("warn"))
            tree.tag_configure("warn", foreground=c("warn"))
            tree.tag_configure("disabled", foreground=c("faint"))
            tree.tag_configure("qc", foreground=c("muted"))
        self.t_log.configure(background=c("surface"), foreground=c("text"), insertbackground=c("text"),
                             selectbackground=c("accent_soft"), font=theme.FONTS.get("mono", ("TkFixedFont", 9)))
        self.t_log.tag_configure("WARNING", foreground=c("warn"))
        self.t_log.tag_configure("ERROR", foreground=c("danger"))
        self.t_log.tag_configure("CRITICAL", foreground=c("danger"))
        self.t_log.tag_configure("DEBUG", foreground=c("muted"))
        self._update_engine_button()

    def _page(self, title: str, subtitle: str) -> tuple[ttk.Frame, ttk.Frame]:
        """A page: title and actions on top, then a card for the content. Returns (actions, card)."""
        page = ttk.Frame(self.content)
        page.grid(row=0, column=0, sticky="nsew")
        head = ttk.Frame(page)
        head.pack(fill="x", pady=(0, PAD))
        left = ttk.Frame(head)
        left.pack(side="left")
        ttk.Label(left, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text=subtitle, style="Subtitle.TLabel").pack(anchor="w")
        actions = ttk.Frame(head)
        actions.pack(side="right", anchor="s")
        card = ttk.Frame(page, style="Card.TFrame", padding=theme.CARD_PAD)
        card.pack(fill="both", expand=True)
        self.pages[title] = page
        return actions, card

    def _actions(self, parent: tk.Misc, buttons: list[tuple[str, Any]]) -> None:
        for text, cmd in buttons:
            if text == "|":
                ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=PAD // 2, pady=4)
            else:
                primary = text.startswith("Add") or text.endswith("settings…")
                ttk.Button(parent, text=text, command=cmd, style="Accent.TButton" if primary else "TButton"
                           ).pack(side="left", padx=(4, 0))

    def _holder(self, card: ttk.Frame) -> ttk.Frame:
        holder = ttk.Frame(card, style="Inner.TFrame")
        holder.pack(fill="both", expand=True)
        return holder

    def select_page(self, title: str) -> None:
        self.current = title
        self.pages[title].tkraise()
        for t, b in self.nav.items():
            b.state(["selected"] if t == title else ["!selected"])
        self._refresh_current()

    def cycle_theme(self) -> None:
        cfg = copy.deepcopy(self.cfg)
        cfg["theme"] = THEME_CYCLE.get(cfg.get("theme", "system"), "system")
        try:
            self.mgr.save(cfg)
        except OSError:
            pass
        self.cfg = self.mgr.snapshot()
        theme.apply(self.root, self.cfg["theme"])
        self.l_status.configure(text=f"Appearance: {self.cfg['theme']}")

    def _build_devices(self) -> None:
        actions, card = self._page("Instruments", PAGES[0][2])
        self._actions(actions, [("Add instrument", self.add_device), ("Edit", self.edit_device),
                                ("Remove", self.remove_device), ("|", None), ("Enable / disable", self.toggle_device),
                                ("Reconnect", self.restart_device)])
        holder = self._holder(card)
        self.t_dev = make_tree(holder, [
            ("name", "Name", 220), ("model", "Instrument", 220), ("protocol", "Protocol", 80), ("link", "Link", 170),
            ("state", "Status", 150), ("peer", "Connected from / detail", 200), ("last", "Last message", 140),
            ("msgs", "Messages", 80), ("errors", "Errors", 60)], selectmode="browse")
        self.t_dev.bind("<Double-1>", lambda e: self.edit_device())
        self.l_empty_dev = ttk.Label(card, style="CardHint.TLabel",
                                     text="No instruments yet. Click 'Add instrument', pick the analyzer model and how it is "
                                          "connected (network or serial).")

    def _build_imaging(self) -> None:
        actions, card = self._page("Imaging", PAGES[1][2])
        self._actions(actions, [("Retry selected study", self.retry_imaging_selected),
                                ("Retry all waiting", lambda: self.retry_imaging(None)), ("|", None),
                                ("Imaging settings…", self.edit_imaging)])
        head = ttk.Frame(card, style="Inner.TFrame")
        head.pack(fill="x", pady=(0, PAD), padx=4)
        self.l_img_state = ttk.Label(head, text="", style="CardPillNeutral.TLabel")
        self.l_img_state.pack(anchor="w")
        self.l_img_queue = ttk.Label(head, text="", style="CardHint.TLabel", wraplength=1000, justify="left")
        self.l_img_queue.pack(anchor="w", pady=(6, 0))
        holder = self._holder(card)
        self.t_img = make_tree(holder, [
            ("time", "Received", 160), ("patient", "Patient", 180), ("accession", "Accession", 110),
            ("modality", "Modality", 70), ("desc", "Study", 180), ("from", "From", 110), ("images", "Images", 60),
            ("delivery", "Delivery", 260), ("problem", "Problem", 320)])

    def _build_results(self) -> None:
        actions, card = self._page("Results", PAGES[2][2])
        self._actions(actions, [("Open", self.open_report), ("Export CSV…", self.export_results)])
        bar = ttk.Frame(card, style="Inner.TFrame")
        bar.pack(fill="x", pady=(0, PAD), padx=4)
        self.v_search = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.v_search, width=30)
        e.pack(side="left")
        e.insert(0, "")
        e.bind("<Return>", lambda ev: self.refresh_results())
        ttk.Label(bar, text="Search specimen, patient… then Enter", style="CardHint.TLabel").pack(side="left",
                                                                                               padx=(6, PAD * 2))
        self.v_rdev = tk.StringVar(value="All")
        self.cb_rdev = ttk.Combobox(bar, textvariable=self.v_rdev, state="readonly", width=22)
        self.cb_rdev.pack(side="left", padx=4)
        self.cb_rdev.bind("<<ComboboxSelected>>", lambda ev: self.refresh_results())
        self.v_period = tk.StringVar(value="Last 7 days")
        cb = ttk.Combobox(bar, textvariable=self.v_period, state="readonly", width=12,
                          values=["Today", "Last 7 days", "Last 30 days", "All"])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda ev: self.refresh_results())
        self.v_hideqc = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Hide QC", variable=self.v_hideqc, command=self.refresh_results,
                        style="Card.TCheckbutton").pack(side="left", padx=PAD)
        ttk.Button(bar, text="Refresh", command=self.refresh_results).pack(side="right")
        holder = self._holder(card)
        self.t_res = make_tree(holder, [
            ("time", "Received", 150), ("device", "Instrument", 170), ("specimen", "Specimen", 140),
            ("pid", "Patient ID", 120), ("pname", "Patient", 190), ("tests", "Tests", 60), ("abn", "Abnormal", 70),
            ("kind", "Type", 60), ("delivery", "Delivery", 140)])
        self.t_res.bind("<Double-1>", lambda e: self.open_report())

    def _build_delivery(self) -> None:
        actions, card = self._page("Delivery", PAGES[3][2])
        self._actions(actions, [("Test", self.test_selected_destination), ("Send now", self.flush_destination),
                                ("Retry failed", self.retry_failed), ("|", None), ("Edit", self.edit_destination),
                                ("Remove", self.remove_destination), ("Add destination", self.add_destination)])
        top = self._holder(card)
        self.t_dst = make_tree(top, [
            ("name", "Destination", 200), ("type", "Type", 90), ("target", "Target", 300), ("sched", "Schedule", 120),
            ("pending", "Waiting", 70), ("sent", "Sent", 70), ("failed", "Failed", 70), ("last", "Last error", 320)],
            height=6, selectmode="browse")
        self.t_dst.bind("<Double-1>", lambda e: self.edit_destination())
        page = self.pages["Delivery"]
        card.pack_configure(expand=False)
        head = ttk.Frame(page)
        head.pack(fill="x", pady=(PAD * 2, PAD))
        ttk.Label(head, text="Failed deliveries", style="Section.TLabel").pack(side="left")
        ttk.Label(head, text="not retried automatically", style="Hint.TLabel").pack(side="left", padx=PAD)
        ttk.Button(head, text="Retry selected", command=self.retry_selected).pack(side="right")
        card2 = ttk.Frame(page, style="Card.TFrame", padding=theme.CARD_PAD)
        card2.pack(fill="both", expand=True)
        self.t_fail = make_tree(self._holder(card2), [
            ("time", "Last attempt", 150), ("dest", "Destination", 160), ("specimen", "Specimen", 130),
            ("device", "Instrument", 150), ("attempts", "Attempts", 70), ("code", "Code", 60), ("error", "Error", 420)],
            height=8)

    def _build_messages(self) -> None:
        actions, card = self._page("Messages", PAGES[4][2])
        self._actions(actions, [("View", self.open_message), ("Refresh", self.refresh_messages)])
        holder = self._holder(card)
        self.t_msg = make_tree(holder, [
            ("time", "Time", 150), ("device", "Instrument", 170), ("dir", "Dir", 45), ("protocol", "Protocol", 80),
            ("type", "Type", 80), ("sender", "Sender", 200), ("size", "Bytes", 70), ("reports", "Reports", 60),
            ("warn", "Warnings", 300)])
        self.t_msg.bind("<Double-1>", lambda e: self.open_message())

    def _build_log(self) -> None:
        actions, card = self._page("Log", PAGES[5][2])
        self.v_loglevel = tk.StringVar(value="INFO")
        ttk.Label(actions, text="Show").pack(side="left", padx=(0, 4))
        ttk.Combobox(actions, textvariable=self.v_loglevel, values=["DEBUG", "INFO", "WARNING", "ERROR"],
                     state="readonly", width=10).pack(side="left")
        self.v_follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="Follow", variable=self.v_follow).pack(side="left", padx=PAD)
        self._actions(actions, [("Clear", lambda: self.t_log.delete("1.0", "end")),
                                ("Open log folder", lambda: _open_path(paths.log_dir()))])
        frame = self._holder(card)
        self.t_log = tk.Text(frame, wrap="none", height=20, borderwidth=0, highlightthickness=0, padx=6, pady=4)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.t_log.yview)
        self.t_log.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.t_log.pack(fill="both", expand=True)

    # ================================================================== refresh
    def _poll_events(self) -> None:
        changed_devices = False
        try:
            for _ in range(500):
                kind, data = self.engine.events.get_nowait()
                if kind == "device":
                    self.statuses[data.device_id] = data
                    changed_devices = True
                elif kind == "message":
                    self._dirty["results"] = self._dirty["messages"] = True
                    self._dirty["delivery"] = True
                elif kind == "delivery":
                    self._dirty["delivery"] = True
                    self._dirty["results"] = True
                elif kind == "engine":
                    self._update_engine_button()
                elif kind == "plugin":
                    self._update_links()
                    self._dirty["imaging"] = True
                elif kind == "imaging":
                    self._dirty["imaging"] = True
        except Exception:
            pass
        if changed_devices:
            self.refresh_devices()
        self._drain_log()
        if not self.quitting:
            self.root.after(250, self._poll_events)

    def _periodic(self) -> None:
        try:
            self._update_kpis()
            self._refresh_current()
        except Exception:
            log.exception("GUI refresh failed")
        if not self.quitting:
            self.root.after(2000, self._periodic)

    def _refresh_current(self) -> None:
        tab = self.current
        if tab == "Results" and self._dirty["results"]:
            self.refresh_results()
        elif tab == "Delivery" and self._dirty["delivery"]:
            self.refresh_delivery()
        elif tab == "Messages" and self._dirty["messages"]:
            self.refresh_messages()
        elif tab == "Imaging":
            self.refresh_imaging()  # queue states change on their own (retries, holds), so always refresh

    def _drain_log(self) -> None:
        feed = log_feed()
        if feed is None:
            return
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        minimum = levels.get(self.v_loglevel.get(), 20)
        added = False
        for _ in range(300):
            try:
                rec = feed.queue.get_nowait()
            except Exception:
                break
            if rec.levelno < minimum:
                continue
            self.t_log.insert("end", feed.format(rec) + "\n", rec.levelname)
            added = True
        if added:
            lines = int(self.t_log.index("end-1c").split(".")[0])
            if lines > 5000:
                self.t_log.delete("1.0", f"{lines - 4000}.0")
            if self.v_follow.get():
                self.t_log.see("end")

    def _update_engine_button(self) -> None:
        running = self.engine.running
        self.b_engine.configure(text="Stop receiving" if running else "Start receiving",
                                style="TButton" if running else "Accent.TButton")
        self.l_receiving.configure(text="●  Receiving" if running else "●  Stopped",
                                   style="PillOk.TLabel" if running else "PillWarn.TLabel")
        self._update_links()

    def _update_links(self) -> None:
        """One chip per enabled integration in the sidebar; nothing when none is on."""
        for w in self.side_links.winfo_children():
            w.destroy()
        for _pid, (name, st) in sorted(self.engine.link_states().items()):
            if st.ok:
                style, text = "PillOk.TLabel", f"{name}: {st.text or 'connected'}"
            elif st.ok is False:
                style, text = "PillDanger.TLabel", f"{name}: offline"
            else:
                style, text = "PillNeutral.TLabel", f"{name}: {st.text or 'checking…'}"
            chip = ttk.Label(self.side_links, text=text, style=style, wraplength=190)
            chip.pack(anchor="w", pady=(0, 4))
            if st.ok is False and st.text:
                ttk.Label(self.side_links, text=st.text, style="SidebarHint.TLabel", wraplength=190,
                          justify="left").pack(anchor="w", pady=(0, 4))

    def _update_kpis(self) -> None:
        devices = [d for d in self.cfg.get("devices", []) if d.get("enabled", True)]
        online = sum(1 for d in devices if self.statuses.get(d["id"], DeviceStatus(d["id"])).state == "connected")
        self.kpis["connected"].configure(text=f"{online}/{len(devices)}")
        self.kpis["today"].configure(text=str(self.db.counts_today()["results"]))
        stats = self.db.outbox_stats()
        known = {d["id"] for d in self.cfg.get("destinations", [])}
        pending = sum(v.get("pending", 0) for k, v in stats.items() if k in known)
        failed = sum(v.get("failed", 0) for k, v in stats.items() if k in known)
        self.kpis["pending"].configure(text=str(pending))
        self.kpis["failed"].configure(text=str(failed), foreground=theme.color("danger") if failed else theme.color("text"))
        status = self.engine.imaging_status() if (self.cfg.get("imaging") or {}).get("enabled") else None
        if status is not None:
            totals = status["counts"]["totals"]
            self.kpis["images"].configure(text=str(totals["pending"] + totals["sending"] + totals["held"]))
        else:
            self.kpis["images"].configure(text="off")
        self._update_engine_button()

    def refresh_devices(self) -> None:
        rows = []
        for d in self.cfg.get("devices", []):
            p = find_profile(d.get("profile", ""))
            t = d.get("transport") or {}
            if t.get("type") == "serial":
                link = f"{t.get('port')} @ {t.get('baudrate', 9600)}"
            elif t.get("type") == "tcp_client":
                link = f"→ {t.get('host')}:{t.get('port')}"
            else:
                link = f"listen :{t.get('port')}"
            st = self.statuses.get(d["id"])
            enabled = d.get("enabled", True)
            state = "Disabled" if not enabled else STATE_LABELS.get(st.state, st.state) if st else "Stopped"
            detail = ", ".join(st.peers) if st and st.peers else (st.detail if st else "")
            tags: tuple[str, ...] = ()
            if not enabled:
                tags = ("disabled",)
            elif st and st.state == "connected":
                tags = ("connected",)
            elif st and st.state == "error":
                tags = ("error",)
            protocol = (d.get("options") or {}).get("protocol") or (p.protocol if p else "?")
            rows.append((d["id"], (d.get("name"), p.label if p else d.get("profile"), protocol.upper(), link, state, detail,
                                   local_ts(st.last_message_at) if st else "", st.messages if st else 0,
                                   st.errors if st else 0), tags))
        replace_rows(self.t_dev, rows)
        if rows:
            self.l_empty_dev.pack_forget()
        else:
            self.l_empty_dev.pack(pady=PAD * 3)
        names = ["All"] + [d.get("name", d["id"]) for d in self.cfg.get("devices", [])]
        self.cb_rdev.configure(values=names)

    def _device_name(self, device_id: str) -> str:
        d = next((d for d in self.cfg.get("devices", []) if d["id"] == device_id), None)
        return d.get("name", device_id) if d else device_id

    def refresh_results(self) -> None:
        self._dirty["results"] = False
        device_id = ""
        if self.v_rdev.get() != "All":
            device_id = next((d["id"] for d in self.cfg.get("devices", []) if d.get("name") == self.v_rdev.get()), "")
        since = None
        period = self.v_period.get()
        now = datetime.now().astimezone()
        if period == "Today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "Last 7 days":
            since = now - timedelta(days=7)
        elif period == "Last 30 days":
            since = now - timedelta(days=30)
        rows_db = self.db.recent_reports(limit=2000, search=self.v_search.get().strip(), device_id=device_id,
                                         since=since.astimezone(UTC).isoformat() if since else None,
                                         include_qc=not self.v_hideqc.get())
        rows = []
        for r in rows_db:
            statuses = (r["delivery"] or "").split(",") if r["delivery"] else []
            if not statuses:
                delivery = "not routed"
            elif all(s == "sent" for s in statuses):
                delivery = "sent"
            elif any(s == "failed" for s in statuses):
                delivery = "FAILED"
            else:
                delivery = "waiting"
            tags = ("qc",) if r["is_qc"] else ("abnormal",) if r["abnormal_count"] else ()
            rows.append((str(r["id"]), (local_ts(r["received_at"]), self._device_name(r["device_id"]), r["specimen_id"] or "",
                                        r["patient_id"] or "", r["patient_name"] or "", r["observation_count"],
                                        r["abnormal_count"] or "", "QC" if r["is_qc"] else "", delivery), tags))
        replace_rows(self.t_res, rows)

    def refresh_delivery(self) -> None:
        self._dirty["delivery"] = False
        status = self.engine.destination_status()
        names = {d["id"]: d.get("name", d["id"]) for d in self.cfg.get("destinations", [])}
        rows = []
        for d in self.cfg.get("destinations", []):
            st = status.get(d["id"], {})
            sched = d.get("schedule") or {}
            mode = sched.get("mode", "realtime")
            sched_text = "Real-time" if mode == "realtime" else (
                f"Every {sched.get('interval_minutes')} min" if mode == "interval" else f"cron {sched.get('cron')}")
            owner = plugins.lab_destination_owner(self.cfg, d.get("type", ""), only_enabled=False)
            if owner is not None:
                target = owner[0].describe_destination(d, owner[1])
                if not plugins.is_enabled(self.cfg, owner[0].id):
                    target += " (integration turned off)"
            else:
                target = d.get("url") or (f"{d.get('host')}:{d.get('port')}" if d.get("type") == "hl7_mllp"
                                          else d.get("folder", ""))
            tags = ("disabled",) if not d.get("enabled", True) else ("failed",) if st.get("failed") else ()
            rows.append((d["id"], (d.get("name"), d.get("type"), target, sched_text, st.get("pending", 0),
                                   st.get("sent", 0), st.get("failed", 0), st.get("last_error", "")), tags))
        replace_rows(self.t_dst, rows)
        failed = []
        for f in self.db.failed_items():
            failed.append((str(f["id"]), (local_ts(f["last_attempt_at"]), names.get(f["destination_id"], f["destination_id"]),
                                          f["specimen_id"] or "", self._device_name(f["device_id"]), f["attempts"],
                                          f["response_code"] or "", f["last_error"] or ""), ()))
        replace_rows(self.t_fail, failed)

    def refresh_imaging(self) -> None:
        self._dirty["imaging"] = False
        img_cfg = self.cfg.get("imaging") or {}
        status = self.engine.imaging_status()
        if not img_cfg.get("enabled") or status is None or not status["running"]:
            self.l_img_state.configure(text="Imaging is off", style="CardPillNeutral.TLabel")
            self.l_img_queue.configure(
                text="Open 'Imaging settings…' to receive images from CT, MRI, X-ray and ultrasound devices and "
                     "forward them to a PACS, a DICOMweb server or another system.")
            if status is None:
                replace_rows(self.t_img, [])
                return
        elif status["error"]:
            self.l_img_state.configure(text=status["error"], style="CardPillDanger.TLabel")
        else:
            host, port = status["listening_on"] or ("", img_cfg.get("port"))
            nodes = status["allowed_nodes"]
            self.l_img_state.configure(
                style="CardPillOk.TLabel",
                text=f"●  Listening as {img_cfg.get('ae_title')} on port {port} · {len(nodes)} device(s) allowed"
                     + (f" ({', '.join(sorted({n.get('ae_title', '') for n in nodes})[:6])})" if nodes else "")
                     + (" · accepting any device" if img_cfg.get("accept_unknown_nodes") else ""))
        if status is not None:
            totals = status["counts"]["totals"]
            parts = [f"{status['counts']['received_24h']} image(s) in the last 24 h",
                     f"{totals['pending'] + totals['sending']} waiting to send", f"{totals['held']} waiting for an order",
                     f"{totals['failed']} failed"]
            for d in status["destinations"]:
                if d["last_error"]:
                    parts.append(f"{d['name']}: {d['last_error']}")
            if status.get("last_refused"):
                parts.append(f"Last refused: {status['last_refused']}")
            self.l_img_queue.configure(text=" · ".join(parts))
        rows = []
        names = {d.get("id"): d.get("name") or d.get("id") for d in img_cfg.get("destinations") or []}
        for st in self.engine.imaging.store.recent_studies(limit=200):
            dests = st["destinations"]

            def summary(entry: dict[str, Any]) -> str:
                c = entry["counts"]
                if c.get("failed"):
                    return f"failed ({c['failed']})"
                if c.get("held"):
                    return "waiting for order"
                if c.get("pending") or c.get("sending"):
                    return "sending"
                return "delivered" if c.get("done") else ""

            problem = next((e["last_error"] for e in dests.values() if e.get("last_error")), "") or ""
            delivery = " · ".join(f"{names.get(k, k)}: {summary(e) or '–'}" for k, e in sorted(dests.items())) or "–"
            states_ = {k for e in dests.values() for k in e["counts"]}
            tags = ("problem",) if "failed" in states_ else ("waiting",) if states_ & {"held", "pending", "sending"} else ()
            rows.append((st["study_instance_uid"] or "unknown", (
                datetime.fromtimestamp(st["last_received"]).strftime("%Y-%m-%d %H:%M:%S"), st["patient_name"] or "",
                st["accession_number"] or "", st["modality"] or "", st["study_description"] or "",
                st["calling_ae"] or "", st["instances"], delivery, problem), tags))
        replace_rows(self.t_img, rows)

    def edit_imaging(self) -> None:
        dlg = ImagingDialog(self.root, self.cfg)
        self.root.wait_window(dlg)
        if dlg.result and self._commit(dlg.result):
            self.root.after(800, self.refresh_imaging)

    def retry_imaging_selected(self) -> None:
        sel = self._selected(self.t_img)
        if sel:
            self.retry_imaging(sel)

    def retry_imaging(self, study_uid: str | None) -> None:
        fut = self.engine.call(self.engine.retry_imaging(study_uid))
        fut.add_done_callback(lambda f: self.root.after(500, self.refresh_imaging))

    def refresh_messages(self) -> None:
        self._dirty["messages"] = False
        rows = []
        for m in self.db.recent_messages(limit=1000):
            warn = m["warnings"] or ""
            rows.append((str(m["id"]), (local_ts(m["received_at"]), self._device_name(m["device_id"]),
                                        "in" if m["direction"] == "in" else "out", m["protocol"], m["message_type"],
                                        m["sender"] or "", m["size"] or 0, m["report_count"],
                                        warn.strip("[]").replace('"', "")), ("warn",) if warn else ()))
        replace_rows(self.t_msg, rows)

    # ================================================================== config changes
    def _commit(self, new_cfg: dict[str, Any]) -> bool:
        problems = validate(new_cfg)
        if problems:
            messagebox.showerror("Configuration problem", "\n".join(problems), parent=self.root)
            return False
        try:
            self.mgr.save(new_cfg)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self.root)
            return False
        self.cfg = self.mgr.snapshot()
        self.engine.call(self.engine.apply_config(self.cfg))
        self.statuses = {k: v for k, v in self.statuses.items() if any(d["id"] == k for d in self.cfg["devices"])}
        self.refresh_devices()
        self._dirty.update(results=True, delivery=True)
        self.refresh_delivery()
        return True

    def _selected(self, tree: ttk.Treeview) -> str | None:
        sel = tree.selection()
        return sel[0] if sel else None

    def add_device(self) -> None:
        used = {int((d.get("transport") or {}).get("port", 0) or 0) for d in self.cfg.get("devices", [])}
        port = next(p for p in range(5000, 6000) if p not in used)
        dlg = DeviceDialog(self.root, new_device("generic_astm", port=port), is_new=True)
        self.root.wait_window(dlg)
        if dlg.result:
            cfg = copy.deepcopy(self.cfg)
            cfg["devices"].append(dlg.result)
            self._commit(cfg)

    def edit_device(self) -> None:
        did = self._selected(self.t_dev)
        if not did:
            return
        cfg = copy.deepcopy(self.cfg)
        idx = next(i for i, d in enumerate(cfg["devices"]) if d["id"] == did)
        dlg = DeviceDialog(self.root, cfg["devices"][idx], is_new=False)
        self.root.wait_window(dlg)
        if dlg.result:
            cfg["devices"][idx] = dlg.result
            self._commit(cfg)

    def remove_device(self) -> None:
        did = self._selected(self.t_dev)
        if not did:
            return
        name = self._device_name(did)
        if not messagebox.askyesno("Remove instrument", f"Stop reading from {name} and remove it?\n\n"
                                   "Results already received are kept.", parent=self.root):
            return
        cfg = copy.deepcopy(self.cfg)
        cfg["devices"] = [d for d in cfg["devices"] if d["id"] != did]
        for dest in cfg.get("destinations", []):
            dest["devices"] = [x for x in dest.get("devices", []) if x != did]
        self._commit(cfg)

    def toggle_device(self) -> None:
        did = self._selected(self.t_dev)
        if not did:
            return
        cfg = copy.deepcopy(self.cfg)
        for d in cfg["devices"]:
            if d["id"] == did:
                d["enabled"] = not d.get("enabled", True)
        self._commit(cfg)

    def restart_device(self) -> None:
        did = self._selected(self.t_dev)
        if did:
            self.engine.call(self.engine.restart_device(did))

    def _tester(self, dest: dict[str, Any]) -> None:
        self.l_status.configure(text=f"Testing {dest.get('name')}…")
        fut = self.engine.call(self.engine.test_destination(dest))

        def done(f) -> None:
            try:
                msg, ok = f.result(), True
            except Exception as exc:
                msg, ok = str(exc) or exc.__class__.__name__, False
            self.root.after(0, lambda: (messagebox.showinfo if ok else messagebox.showerror)(
                "Connection test", f"{dest.get('name')}: {msg}", parent=self.root))
            self.root.after(0, self._update_engine_button)

        fut.add_done_callback(done)

    def add_destination(self) -> None:
        dlg = DestinationDialog(self.root, new_destination("http"), self.cfg.get("devices", []), True, self._tester,
                                self.cfg)
        self.root.wait_window(dlg)
        if dlg.result:
            cfg = copy.deepcopy(self.cfg)
            cfg["destinations"].append(dlg.result)
            self._commit(cfg)

    def edit_destination(self) -> None:
        did = self._selected(self.t_dst)
        if not did:
            return
        cfg = copy.deepcopy(self.cfg)
        idx = next(i for i, d in enumerate(cfg["destinations"]) if d["id"] == did)
        dlg = DestinationDialog(self.root, cfg["destinations"][idx], cfg.get("devices", []), False, self._tester, cfg)
        self.root.wait_window(dlg)
        if dlg.result:
            cfg["destinations"][idx] = dlg.result
            self._commit(cfg)

    def remove_destination(self) -> None:
        did = self._selected(self.t_dst)
        if not did:
            return
        name = next((d.get("name") for d in self.cfg["destinations"] if d["id"] == did), did)
        if not messagebox.askyesno("Remove destination", f"Stop sending results to {name}?", parent=self.root):
            return
        cfg = copy.deepcopy(self.cfg)
        cfg["destinations"] = [d for d in cfg["destinations"] if d["id"] != did]
        self._commit(cfg)

    def test_selected_destination(self) -> None:
        did = self._selected(self.t_dst)
        dest = next((d for d in self.cfg["destinations"] if d["id"] == did), None)
        if dest:
            self._tester(dest)

    def flush_destination(self) -> None:
        did = self._selected(self.t_dst)
        if did:
            fut = self.engine.call(self.engine.flush_now(did))
            fut.add_done_callback(lambda f: self.root.after(0, self.refresh_delivery))

    def retry_failed(self) -> None:
        did = self._selected(self.t_dst)
        fut = self.engine.call(self.engine.retry_failed(did))
        fut.add_done_callback(lambda f: self.root.after(300, self.refresh_delivery))

    def retry_selected(self) -> None:
        ids = [int(i) for i in self.t_fail.selection()]
        if ids:
            fut = self.engine.call(self.engine.retry_failed(None, ids))
            fut.add_done_callback(lambda f: self.root.after(300, self.refresh_delivery))

    def edit_settings(self) -> None:
        dlg = SettingsDialog(self.root, self.cfg, self.mgr.secrets.available)
        self.root.wait_window(dlg)
        if dlg.result:
            old_theme = self.cfg.get("theme")
            if self._commit(dlg.result):
                logging.getLogger("labsync").setLevel(self.cfg.get("log_level", "INFO"))
                self.root.title(self.cfg.get("app_name", "LabSync"))
                self.l_instance.configure(text=self.cfg.get("instance_id", ""))
                if self.cfg.get("theme") != old_theme:
                    theme.apply(self.root, self.cfg.get("theme", "system"))
                self._update_links()

    # ================================================================== viewers
    def open_report(self) -> None:
        rid = self._selected(self.t_res)
        if not rid:
            return
        report = self.db.load_report(int(rid), with_attachments=True)
        if report is None:
            return
        row = self.db.query("SELECT device_id, received_at FROM reports WHERE id=?", (int(rid),))[0]
        raw, _ = self.db.report_message_raw(int(rid))
        dests = {d["id"]: d.get("name", d["id"]) for d in self.cfg.get("destinations", [])}

        def resend(dest_id: str) -> None:
            self.engine.call(self.engine.resend_reports([int(rid)], dest_id))
            self._dirty["results"] = True

        ReportWindow(self.root, report, {"device": self._device_name(row["device_id"]), "received_at": row["received_at"]},
                     raw, self.db.report_delivery(int(rid)), dests, resend)

    def open_message(self) -> None:
        mid = self._selected(self.t_msg)
        if mid:
            values = self.t_msg.item(mid, "values")
            RawMessageWindow(self.root, f"{values[1]} · {values[0]} · {values[3]}", self.db.message_raw(int(mid)))

    def export_results(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile=f"labsync-results-{datetime.now():%Y%m%d}.csv")
        if not path:
            return
        ids = [int(i) for i in self.t_res.get_children("")]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["received_at", "instrument", "specimen_id", "patient_id", "patient_name", "qc", "code", "name",
                        "value", "units", "reference_range", "flags", "status", "observed_at"])
            for rid in ids:
                rep = self.db.load_report(rid)
                if rep is None:
                    continue
                meta = self.t_res.item(str(rid), "values")
                for o in rep.observations:
                    w.writerow([meta[0], meta[1], rep.specimen.id, rep.patient.id, rep.patient.name.full,
                                "Y" if rep.is_qc else "", o.code, o.name, o.value, o.units, o.reference_range,
                                " ".join(o.flags), o.status, o.observed_at])
        self.l_status.configure(text=f"Exported {len(ids)} reports to {path}")

    # ================================================================== app lifecycle
    def toggle_engine(self) -> None:
        if self.engine.running:
            if not messagebox.askyesno("Stop receiving", "Instruments will not be read until you start again. Continue?",
                                       parent=self.root):
                return
            self.engine.call(self.engine.stop())
        else:
            self.engine.call(self.engine.start())
        self.root.after(500, self._update_engine_button)

    def check_updates(self, silent: bool) -> None:
        def work() -> None:
            try:
                info = updater.check()
            except Exception as exc:
                err = str(exc)
                if not silent:
                    self.root.after(0, lambda: messagebox.showerror("Updates", f"Could not check for updates: {err}",
                                                                    parent=self.root))
                return
            self.root.after(0, lambda: self._offer_update(info, silent))

        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, info, silent: bool) -> None:
        if info is None:
            if not silent:
                messagebox.showinfo("Updates", f"LabSync {__version__} is the latest version.", parent=self.root)
            return
        if not messagebox.askyesno("Update available",
                                   f"LabSync {info.version} is available (you have {__version__}).\n\n"
                                   "Download and install it now? LabSync will close while it installs.", parent=self.root):
            return

        def work() -> None:
            try:
                path = updater.download(info, paths.updates_dir())
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda: (messagebox.showwarning("Update", f"{err}\n\nOpening the release page instead.",
                                                                   parent=self.root), webbrowser.open(info.page_url)))
                return
            self.root.after(0, lambda: (updater.launch_installer(path), self.quit()))

        self.l_status.configure(text=f"Downloading LabSync {info.version}…")
        threading.Thread(target=work, daemon=True).start()

    def about(self) -> None:
        messagebox.showinfo("About LabSync", f"LabSync {__version__}\n\nLaboratory instrument integration.\n"
                                             f"Data folder: {paths.app_home()}", parent=self.root)

    def show(self) -> None:
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

    def on_close(self) -> None:
        if self.cfg.get("minimize_to_tray", True) and (self.tray.available or sys.platform == "darwin"):
            if sys.platform == "darwin":
                self.root.withdraw()
            else:
                self.root.withdraw()
                self.tray.notify("LabSync is still receiving results. Right-click the tray icon to quit.")
            return
        self.quit()

    def quit(self) -> None:
        if self.quitting:
            return
        self.quitting = True
        self.l_status.configure(text="Shutting down…")
        self.root.update_idletasks()
        self.tray.stop()
        self.engine.shutdown_thread()
        self.db.close()
        self.root.after(0, self.root.destroy)


def _open_path(path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
    except Exception as exc:
        messagebox.showerror("LabSync", f"Could not open {path}: {exc}")


def run(mgr: ConfigManager, minimized: bool = False) -> int:
    cfg = mgr.data
    db = Database(paths.database_file())
    engine = Engine(cfg, db)
    engine.start_in_thread()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    theme.apply(root, cfg.get("theme", "system"))
    window = MainWindow(root, mgr, engine, db)
    for problem in validate(cfg):
        log.warning("configuration: %s", problem)
    if cfg.get("auto_start", True):
        engine.call(engine.start())
    if minimized or cfg.get("start_minimized", False):
        root.withdraw() if window.tray.available or sys.platform == "darwin" else root.iconify()
    log.info("LabSync %s started (data folder %s)", __version__, paths.app_home())
    try:
        root.mainloop()
    finally:
        if not window.quitting:
            window.engine.shutdown_thread()
            db.close()
    return 0
