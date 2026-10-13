"""Editing dialogs: instruments, destinations, settings."""

from __future__ import annotations

import copy
import json
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Any

from croniter import croniter

from ..config import AUTH_METHODS, new_destination, validate
from ..devices.catalog import PROFILES, find_profile
from ..protocols import PROTOCOL_LABELS
from ..transport.runner import list_serial_ports
from .common import PAD, Form, center_on

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]


class _Dialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(True, True)
        self.result: Any = None
        self.body = ttk.Frame(self, padding=PAD * 2)
        self.body.pack(fill="both", expand=True)
        self.buttons = ttk.Frame(self, padding=(PAD * 2, 0, PAD * 2, PAD * 2))
        self.buttons.pack(fill="x")
        self.bind("<Escape>", lambda e: self.destroy())

    def finish_layout(self, ok_text: str = "Save") -> None:
        ttk.Button(self.buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(self.buttons, text=ok_text, style="Accent.TButton", command=self._ok).pack(side="right", padx=PAD)
        center_on(self, self.master)
        self.grab_set()
        self.focus_set()

    def _ok(self) -> None:
        try:
            result = self.collect()
        except ValueError as exc:
            messagebox.showerror("Check the form", str(exc), parent=self)
            return
        self.result = result
        self.destroy()

    def collect(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


class DeviceDialog(_Dialog):
    def __init__(self, parent: tk.Misc, device: dict[str, Any], is_new: bool):
        super().__init__(parent, "Add instrument" if is_new else f"Edit {device.get('name', '')}")
        self.device = copy.deepcopy(device)
        t = self.device.setdefault("transport", {"type": "tcp_server", "port": 5000})
        opts = self.device.setdefault("options", {})
        nb = ttk.Notebook(self.body)
        nb.pack(fill="both", expand=True)

        # -- General --
        gen = Form(nb, padding=PAD)
        nb.add(gen, text="General")
        self.v_name = tk.StringVar(value=self.device.get("name", ""))
        gen.add("Name", ttk.Entry(gen, textvariable=self.v_name, width=44))
        self._profiles = sorted(PROFILES, key=lambda p: (p.vendor != "Generic", p.vendor.lower(), p.model.lower()))
        labels = [f"{p.vendor} — {p.model}" for p in self._profiles]
        current = find_profile(self.device.get("profile", "")) or self._profiles[0]
        self.v_profile = tk.StringVar(value=f"{current.vendor} — {current.model}")
        cb = ttk.Combobox(gen, textvariable=self.v_profile, values=labels, state="readonly", width=52)
        cb.bind("<<ComboboxSelected>>", lambda e: self._profile_changed())
        gen.add("Instrument", cb)
        self.l_profile = ttk.Label(gen, style="Hint.TLabel", wraplength=440, justify="left")
        gen.add("", self.l_profile)
        self.v_enabled = tk.BooleanVar(value=self.device.get("enabled", True))
        gen.add("", ttk.Checkbutton(gen, text="Enabled (connect when LabSync starts)", variable=self.v_enabled))

        # -- Connection --
        con = Form(nb, padding=PAD)
        nb.add(con, text="Connection")
        self.con = con
        self.v_ttype = tk.StringVar(value=t.get("type", "tcp_server"))
        rb = ttk.Frame(con)
        for value, text in (("tcp_server", "LabSync listens (analyzer connects to this PC)"),
                            ("tcp_client", "LabSync connects to the analyzer"),
                            ("serial", "Serial port (RS-232 / USB adapter)")):
            ttk.Radiobutton(rb, text=text, value=value, variable=self.v_ttype,
                            command=self._transport_changed).pack(anchor="w")
        con.add("Link", rb)
        self.v_host = tk.StringVar(value=t.get("host", "0.0.0.0" if t.get("type") == "tcp_server" else ""))
        con.add("Address", ttk.Entry(con, textvariable=self.v_host), key="host",
                hint="Listening: 0.0.0.0 accepts on every network card. Client: the analyzer's IP address.")
        self.v_port = tk.StringVar(value=str(t.get("port", 5000)) if t.get("type") != "serial" else "5000")
        con.add("TCP port", ttk.Entry(con, textvariable=self.v_port, width=10), key="tcp_port")
        self.v_allowed = tk.StringVar(value=", ".join(t.get("allowed_peers", []) or []))
        con.add("Allowed IPs", ttk.Entry(con, textvariable=self.v_allowed), key="allowed",
                hint="Optional. Comma-separated IPs or networks (e.g. 192.168.10.25, 10.0.0.0/24).")
        ports = [p for p, _ in list_serial_ports()]
        self.v_sport = tk.StringVar(value=t.get("port", ports[0] if ports else "") if t.get("type") == "serial" else (ports[0] if ports else ""))
        con.add("Serial port", ttk.Combobox(con, textvariable=self.v_sport, values=ports), key="sport")
        self.v_baud = tk.StringVar(value=str(t.get("baudrate", 9600)))
        con.add("Baud rate", ttk.Combobox(con, textvariable=self.v_baud, values=BAUD_RATES, width=10), key="baud")
        self.v_frame = tk.StringVar(value=f"{t.get('bytesize', 8)}{t.get('parity', 'N')}{int(float(t.get('stopbits', 1)))}")
        con.add("Data format", ttk.Combobox(con, textvariable=self.v_frame, values=["8N1", "7E1", "7O1", "8E1", "8O1", "7N2", "8N2"],
                                            width=10), key="frame", hint="Data bits, parity, stop bits.")
        flow = "rtscts" if t.get("rtscts") else "xonxoff" if t.get("xonxoff") else "none"
        self.v_flow = tk.StringVar(value=flow)
        con.add("Flow control", ttk.Combobox(con, textvariable=self.v_flow, values=["none", "rtscts", "xonxoff"],
                                             state="readonly", width=10), key="flow")

        # -- Advanced --
        adv = Form(nb, padding=PAD)
        nb.add(adv, text="Advanced")
        self.v_protocol = tk.StringVar(value=opts.get("protocol", "") or "profile default")
        adv.add("Protocol", ttk.Combobox(adv, textvariable=self.v_protocol,
                                         values=["profile default", *PROTOCOL_LABELS.keys()], state="readonly"),
                hint="Override when the instrument is configured for a different host protocol.")
        self.v_checksum = tk.StringVar(value=opts.get("checksum", "") or "profile default")
        adv.add("ASTM checksum", ttk.Combobox(adv, textvariable=self.v_checksum,
                                              values=["profile default", "strict", "lenient", "ignore"], state="readonly"),
                hint="Strict NAKs bad frames so the analyzer resends them. Use lenient only for non-conforming devices.")
        self.v_encoding = tk.StringVar(value=opts.get("encoding", ""))
        adv.add("Text encoding", ttk.Combobox(adv, textvariable=self.v_encoding,
                                              values=["", "latin-1", "utf-8", "cp1252", "ascii"]),
                hint="Blank = protocol default.")
        self.v_trace = tk.BooleanVar(value=bool(opts.get("trace", False)))
        adv.add("", ttk.Checkbutton(adv, text="Log every byte on the wire (troubleshooting)", variable=self.v_trace))
        rest = {k: v for k, v in opts.items() if k not in ("protocol", "checksum", "encoding", "trace")}
        self.t_opts = tk.Text(adv, height=8, width=60, font=("TkFixedFont", 9))
        self.t_opts.insert("1.0", json.dumps(rest, indent=2) if rest else "{}")
        adv.add("Extra options (JSON)", self.t_opts,
                hint='Profile overrides, e.g. {"astm": {"test_code_component": 3}} or {"answer_queries": false}.')

        self._profile_changed(initial=True)
        self._transport_changed()
        self.finish_layout()

    def _selected_profile(self):
        label = self.v_profile.get()
        for p in self._profiles:
            if f"{p.vendor} — {p.model}" == label:
                return p
        return self._profiles[0]

    def _profile_changed(self, initial: bool = False) -> None:
        p = self._selected_profile()
        maturity = {"stable": "Stable", "beta": "Beta: validate on site",
                    "experimental": "Experimental: confirm the layout with a capture"}[p.maturity]
        self.l_profile.configure(text=f"{PROTOCOL_LABELS.get(p.protocol, p.protocol)} · {p.category} · {maturity}\n{p.notes}".strip())
        if not initial:
            if not self.v_name.get().strip() or self.v_name.get() in {f"{q.vendor} {q.model}" for q in self._profiles}:
                self.v_name.set(f"{p.vendor} {p.model}")
            if p.transport == "serial" and self.v_ttype.get() != "serial":
                self.v_ttype.set("serial")
                self._transport_changed()
            if p.serial:
                self.v_baud.set(str(p.serial.get("baudrate", 9600)))

    def _transport_changed(self) -> None:
        kind = self.v_ttype.get()
        for key in ("host", "tcp_port"):
            self.con.show(key, kind != "serial")
        self.con.show("allowed", kind == "tcp_server")
        for key in ("sport", "baud", "frame", "flow"):
            self.con.show(key, kind == "serial")
        if kind == "tcp_client" and self.v_host.get() == "0.0.0.0":
            self.v_host.set("")
        if kind == "tcp_server" and not self.v_host.get():
            self.v_host.set("0.0.0.0")

    def collect(self) -> dict[str, Any]:
        d = self.device
        d["name"] = self.v_name.get().strip() or self._selected_profile().label
        d["profile"] = self._selected_profile().id
        d["enabled"] = bool(self.v_enabled.get())
        kind = self.v_ttype.get()
        if kind == "serial":
            frame = self.v_frame.get().strip().upper() or "8N1"
            if len(frame) != 3 or frame[0] not in "5678" or frame[1] not in "NEOMS" or frame[2] not in "12":
                raise ValueError("Data format must look like 8N1 or 7E1.")
            if not self.v_sport.get().strip():
                raise ValueError("Choose a serial port.")
            try:
                baud = int(self.v_baud.get())
            except ValueError as exc:
                raise ValueError("Baud rate must be a number.") from exc
            d["transport"] = {"type": "serial", "port": self.v_sport.get().strip(), "baudrate": baud,
                              "bytesize": int(frame[0]), "parity": frame[1], "stopbits": int(frame[2]),
                              "rtscts": self.v_flow.get() == "rtscts", "xonxoff": self.v_flow.get() == "xonxoff"}
        else:
            try:
                port = int(self.v_port.get())
                assert 1 <= port <= 65535
            except (ValueError, AssertionError) as exc:
                raise ValueError("TCP port must be a number between 1 and 65535.") from exc
            host = self.v_host.get().strip()
            if kind == "tcp_client" and not host:
                raise ValueError("Enter the analyzer's IP address or host name.")
            d["transport"] = {"type": kind, "host": host or "0.0.0.0", "port": port}
            if kind == "tcp_server":
                allowed = [a.strip() for a in self.v_allowed.get().split(",") if a.strip()]
                if allowed:
                    import ipaddress

                    for a in allowed:
                        try:
                            ipaddress.ip_network(a, strict=False)
                        except ValueError as exc:
                            raise ValueError(f"{a!r} is not an IP address or network.") from exc
                    d["transport"]["allowed_peers"] = allowed
        try:
            extra = json.loads(self.t_opts.get("1.0", "end").strip() or "{}")
            if not isinstance(extra, dict):
                raise ValueError
        except ValueError as exc:
            raise ValueError("Extra options must be a JSON object, e.g. {}") from exc
        opts = dict(extra)
        if self.v_protocol.get() != "profile default":
            opts["protocol"] = self.v_protocol.get()
        if self.v_checksum.get() != "profile default":
            opts["checksum"] = self.v_checksum.get()
        if self.v_encoding.get().strip():
            opts["encoding"] = self.v_encoding.get().strip()
        if self.v_trace.get():
            opts["trace"] = True
        d["options"] = opts
        return d


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------


class DestinationDialog(_Dialog):
    def __init__(self, parent: tk.Misc, dest: dict[str, Any], devices: list[dict[str, Any]], is_new: bool,
                 tester: Callable[[dict[str, Any]], None]):
        super().__init__(parent, "Add destination" if is_new else f"Edit {dest.get('name', '')}")
        self.dest = copy.deepcopy(dest)
        self.devices = devices
        self.tester = tester
        nb = ttk.Notebook(self.body)
        nb.pack(fill="both", expand=True)

        f = Form(nb, padding=PAD)
        self.f = f
        nb.add(f, text="Destination")
        self.v_name = tk.StringVar(value=self.dest.get("name", ""))
        f.add("Name", ttk.Entry(f, textvariable=self.v_name, width=48))
        self.v_type = tk.StringVar(value=self.dest.get("type", "http"))
        types = ttk.Combobox(f, textvariable=self.v_type, state="readonly",
                             values=["http", "fhir", "hl7_mllp", "file"], width=14)
        types.bind("<<ComboboxSelected>>", lambda e: self._type_changed())
        f.add("Type", types, hint="http: REST/JSON API · fhir: FHIR R4 server · hl7_mllp: LIS/HIS over HL7 · file: drop folder")
        self.v_enabled = tk.BooleanVar(value=self.dest.get("enabled", True))
        f.add("", ttk.Checkbutton(f, text="Enabled", variable=self.v_enabled))

        self.v_url = tk.StringVar(value=self.dest.get("url", ""))
        f.add("URL", ttk.Entry(f, textvariable=self.v_url), key="url")
        self.v_method = tk.StringVar(value=self.dest.get("method", "POST"))
        f.add("Method", ttk.Combobox(f, textvariable=self.v_method, values=["POST", "PUT", "PATCH"], state="readonly",
                                     width=8), key="method")
        self.v_format = tk.StringVar(value=self.dest.get("payload_format", "labsync"))
        f.add("Payload", ttk.Combobox(f, textvariable=self.v_format, values=["labsync", "legacy", "fhir"],
                                      state="readonly", width=12), key="format",
              hint="labsync: documented JSON schema (recommended) · legacy: LabSync 1.x shape · fhir: FHIR Bundle")
        self.v_verify = tk.BooleanVar(value=self.dest.get("verify_tls", True))
        f.add("", ttk.Checkbutton(f, text="Verify TLS certificates", variable=self.v_verify), key="verify")
        self.v_ca = tk.StringVar(value=self.dest.get("ca_bundle", ""))
        ca = ttk.Frame(f)
        ttk.Entry(ca, textvariable=self.v_ca).pack(side="left", fill="x", expand=True)
        ttk.Button(ca, text="Browse…", command=lambda: self.v_ca.set(
            filedialog.askopenfilename(parent=self, filetypes=[("Certificates", "*.pem *.crt *.cer"), ("All", "*")]) or self.v_ca.get())
        ).pack(side="left", padx=(4, 0))
        f.add("Extra CA file", ca, key="ca", hint="Optional PEM file for a private certificate authority.")
        self.v_attach = tk.BooleanVar(value=self.dest.get("include_attachments", False))
        f.add("", ttk.Checkbutton(f, text="Include images (histograms / scattergrams)", variable=self.v_attach),
              key="attach")
        self.t_headers = tk.Text(f, height=3, width=50, font=("TkFixedFont", 9))
        self.t_headers.insert("1.0", "\n".join(f"{k}: {v}" for k, v in (self.dest.get("headers") or {}).items()))
        f.add("Extra headers", self.t_headers, key="headers", hint="One 'Name: value' per line.")

        self.v_host = tk.StringVar(value=self.dest.get("host", ""))
        f.add("Host", ttk.Entry(f, textvariable=self.v_host), key="host")
        self.v_port = tk.StringVar(value=str(self.dest.get("port", 2575)))
        f.add("Port", ttk.Entry(f, textvariable=self.v_port, width=8), key="port")
        self.v_hl7v = tk.StringVar(value=self.dest.get("hl7_version", "2.5.1"))
        f.add("HL7 version", ttk.Combobox(f, textvariable=self.v_hl7v, values=["2.3.1", "2.4", "2.5", "2.5.1"], width=8),
              key="hl7v")
        self.v_rapp = tk.StringVar(value=self.dest.get("receiving_app", ""))
        f.add("Receiving app", ttk.Entry(f, textvariable=self.v_rapp), key="rapp")
        self.v_rfac = tk.StringVar(value=self.dest.get("receiving_facility", ""))
        f.add("Receiving facility", ttk.Entry(f, textvariable=self.v_rfac), key="rfac")
        self.v_folder = tk.StringVar(value=self.dest.get("folder", ""))
        fo = ttk.Frame(f)
        ttk.Entry(fo, textvariable=self.v_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(fo, text="Browse…", command=lambda: self.v_folder.set(
            filedialog.askdirectory(parent=self) or self.v_folder.get())).pack(side="left", padx=(4, 0))
        f.add("Folder", fo, key="folder")
        self.v_ffmt = tk.StringVar(value=self.dest.get("format", "json"))
        f.add("File format", ttk.Combobox(f, textvariable=self.v_ffmt, values=["json", "hl7", "csv", "fhir"],
                                          state="readonly", width=8), key="ffmt")

        # -- Authentication --
        a = Form(nb, padding=PAD)
        self.a = a
        nb.add(a, text="Authentication")
        auth = self.dest.get("auth") or {"method": "none"}
        self.v_auth = tk.StringVar(value=auth.get("method", "none"))
        am = ttk.Combobox(a, textvariable=self.v_auth, values=list(AUTH_METHODS), state="readonly", width=12)
        am.bind("<<ComboboxSelected>>", lambda e: self._auth_changed())
        a.add("Method", am)
        self.v_akh = tk.StringVar(value=auth.get("header", "X-API-Key"))
        a.add("Header name", ttk.Entry(a, textvariable=self.v_akh), key="akh")
        self.v_ak = tk.StringVar(value=auth.get("api_key", ""))
        a.add("API key", ttk.Entry(a, textvariable=self.v_ak, show="•"), key="ak")
        self.v_tok = tk.StringVar(value=auth.get("token", ""))
        a.add("Token", ttk.Entry(a, textvariable=self.v_tok, show="•"), key="tok")
        self.v_user = tk.StringVar(value=auth.get("username", ""))
        a.add("Username", ttk.Entry(a, textvariable=self.v_user), key="user")
        self.v_pw = tk.StringVar(value=auth.get("password", ""))
        a.add("Password", ttk.Entry(a, textvariable=self.v_pw, show="•"), key="pw")
        self.v_turl = tk.StringVar(value=auth.get("token_url", ""))
        a.add("Token URL", ttk.Entry(a, textvariable=self.v_turl), key="turl")
        self.v_cid = tk.StringVar(value=auth.get("client_id", ""))
        a.add("Client ID", ttk.Entry(a, textvariable=self.v_cid), key="cid")
        self.v_cs = tk.StringVar(value=auth.get("client_secret", ""))
        a.add("Client secret", ttk.Entry(a, textvariable=self.v_cs, show="•"), key="cs")
        self.v_scope = tk.StringVar(value=auth.get("scope", ""))
        a.add("Scope", ttk.Entry(a, textvariable=self.v_scope), key="scope")
        ttk.Label(a, text="Secrets are stored in the operating system's credential store when available.",
                  style="Hint.TLabel").grid(row=99, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

        # -- Schedule & filters --
        s = Form(nb, padding=PAD)
        self.s = s
        nb.add(s, text="Schedule & filters")
        sched = self.dest.get("schedule") or {"mode": "realtime"}
        self.v_mode = tk.StringVar(value=sched.get("mode", "realtime"))
        modes = ttk.Frame(s)
        for value, text in (("realtime", "As soon as results arrive"), ("interval", "Every N minutes"),
                            ("cron", "On a cron schedule")):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.v_mode,
                            command=self._mode_changed).pack(anchor="w")
        s.add("Send", modes)
        self.v_interval = tk.StringVar(value=str(sched.get("interval_minutes", 15)))
        s.add("Minutes", ttk.Entry(s, textvariable=self.v_interval, width=8), key="interval")
        self.v_cron = tk.StringVar(value=sched.get("cron", "0 * * * *"))
        self.v_cron.trace_add("write", lambda *_: self._cron_preview())
        s.add("Cron", ttk.Entry(s, textvariable=self.v_cron, width=20), key="cron",
              hint="minute hour day month weekday, e.g. '*/10 * * * *' or '0 18 * * 1-5'")
        self.l_cron = ttk.Label(s, style="Hint.TLabel")
        s.add("", self.l_cron, key="cronp")
        self.lb_dev = tk.Listbox(s, selectmode="multiple", height=min(8, max(3, len(devices))), exportselection=False)
        for i, d in enumerate(devices):
            self.lb_dev.insert("end", d.get("name", d["id"]))
            if d["id"] in (self.dest.get("devices") or []):
                self.lb_dev.selection_set(i)
        s.add("Instruments", self.lb_dev, hint="Select none to send results from every instrument.")
        self.v_qc = tk.BooleanVar(value=self.dest.get("include_qc", False))
        s.add("", ttk.Checkbutton(s, text="Include quality-control results", variable=self.v_qc))
        self.v_max = tk.StringVar(value=str(self.dest.get("max_attempts", 0)))
        s.add("Max attempts", ttk.Entry(s, textvariable=self.v_max, width=8),
              hint="0 = keep retrying with backoff until delivered (recommended).")

        ttk.Button(self.buttons, text="Test connection", command=self._test).pack(side="left")
        self._type_changed()
        self._auth_changed()
        self._mode_changed()
        self.finish_layout()

    def _type_changed(self) -> None:
        t = self.v_type.get()
        web = t in ("http", "fhir")
        for k in ("url", "verify", "ca", "headers"):
            self.f.show(k, web)
        for k in ("method", "format", "attach"):
            self.f.show(k, t == "http")
        for k in ("host", "port", "hl7v", "rapp", "rfac"):
            self.f.show(k, t == "hl7_mllp")
        for k in ("folder", "ffmt"):
            self.f.show(k, t == "file")

    def _auth_changed(self) -> None:
        m = self.v_auth.get()
        groups = {"api_key": ("akh", "ak"), "bearer": ("tok",), "basic": ("user", "pw"),
                  "oauth2": ("turl", "cid", "cs", "scope")}
        for keys in groups.values():
            for k in keys:
                self.a.show(k, False)
        for k in groups.get(m, ()):
            self.a.show(k, True)

    def _mode_changed(self) -> None:
        m = self.v_mode.get()
        self.s.show("interval", m == "interval")
        for k in ("cron", "cronp"):
            self.s.show(k, m == "cron")
        self._cron_preview()

    def _cron_preview(self) -> None:
        expr = self.v_cron.get().strip()
        if croniter.is_valid(expr):
            it = croniter(expr, datetime.now())
            nxt = [it.get_next(datetime).strftime("%a %d %b %H:%M") for _ in range(3)]
            self.l_cron.configure(text="Next: " + " · ".join(nxt))
        else:
            self.l_cron.configure(text="Not a valid cron expression")

    def collect(self) -> dict[str, Any]:
        d = self.dest
        t = self.v_type.get()
        if t != d.get("type"):
            fresh = new_destination(t)
            fresh["id"] = d["id"]
            d = fresh
        d["name"] = self.v_name.get().strip() or d.get("name")
        d["type"] = t
        d["enabled"] = bool(self.v_enabled.get())
        if t in ("http", "fhir"):
            d["url"] = self.v_url.get().strip()
            d["verify_tls"] = bool(self.v_verify.get())
            d["ca_bundle"] = self.v_ca.get().strip()
            headers = {}
            for line in self.t_headers.get("1.0", "end").splitlines():
                if line.strip():
                    if ":" not in line:
                        raise ValueError(f"Header line {line!r} must look like 'Name: value'.")
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
            d["headers"] = headers
            if t == "http":
                d["method"] = self.v_method.get()
                d["payload_format"] = self.v_format.get()
                d["include_attachments"] = bool(self.v_attach.get())
            auth: dict[str, Any] = {"method": self.v_auth.get()}
            if auth["method"] == "api_key":
                auth.update(header=self.v_akh.get().strip() or "X-API-Key", api_key=self.v_ak.get())
            elif auth["method"] == "bearer":
                auth["token"] = self.v_tok.get()
            elif auth["method"] == "basic":
                auth.update(username=self.v_user.get(), password=self.v_pw.get())
            elif auth["method"] == "oauth2":
                auth.update(token_url=self.v_turl.get().strip(), client_id=self.v_cid.get().strip(),
                            client_secret=self.v_cs.get(), scope=self.v_scope.get().strip())
            d["auth"] = auth
            if not d["verify_tls"] and not messagebox.askyesno(
                    "TLS verification off",
                    "Without certificate verification, patient data can be intercepted. Continue?", parent=self):
                raise ValueError("TLS verification left on.")
        elif t == "hl7_mllp":
            d["host"] = self.v_host.get().strip()
            try:
                d["port"] = int(self.v_port.get())
            except ValueError as exc:
                raise ValueError("Port must be a number.") from exc
            d["hl7_version"] = self.v_hl7v.get().strip() or "2.5.1"
            d["receiving_app"] = self.v_rapp.get().strip()
            d["receiving_facility"] = self.v_rfac.get().strip()
        elif t == "file":
            d["folder"] = self.v_folder.get().strip()
            d["format"] = self.v_ffmt.get()
        try:
            interval = float(self.v_interval.get() or 15)
            max_attempts = int(self.v_max.get() or 0)
        except ValueError as exc:
            raise ValueError("Minutes and max attempts must be numbers.") from exc
        d["schedule"] = {"mode": self.v_mode.get(), "interval_minutes": interval, "cron": self.v_cron.get().strip()}
        d["devices"] = [self.devices[i]["id"] for i in self.lb_dev.curselection()]
        d["include_qc"] = bool(self.v_qc.get())
        d["max_attempts"] = max_attempts
        problems = validate({"devices": [], "destinations": [d]})
        if problems:
            raise ValueError("\n".join(problems))
        return d

    def _test(self) -> None:
        try:
            d = self.collect()
        except ValueError as exc:
            messagebox.showerror("Check the form", str(exc), parent=self)
            return
        self.tester(d)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class SettingsDialog(_Dialog):
    def __init__(self, parent: tk.Misc, cfg: dict[str, Any], keyring_available: bool):
        super().__init__(parent, "Settings")
        self.cfg = copy.deepcopy(cfg)
        f = Form(self.body)
        f.pack(fill="both", expand=True)
        self.v_app = tk.StringVar(value=cfg.get("app_name", "LabSync"))
        f.add("Window title", ttk.Entry(f, textvariable=self.v_app, width=40))
        self.v_inst = tk.StringVar(value=cfg.get("instance_id", ""))
        f.add("Instance ID", ttk.Entry(f, textvariable=self.v_inst),
              hint="Identifies this workstation in every payload it sends.")
        f.section("Behaviour")
        self.v_auto = tk.BooleanVar(value=cfg.get("auto_start", True))
        f.add("", ttk.Checkbutton(f, text="Start receiving when LabSync opens", variable=self.v_auto))
        self.v_min = tk.BooleanVar(value=cfg.get("start_minimized", False))
        f.add("", ttk.Checkbutton(f, text="Start minimised", variable=self.v_min))
        self.v_tray = tk.BooleanVar(value=cfg.get("minimize_to_tray", True))
        f.add("", ttk.Checkbutton(f, text="Closing the window keeps LabSync running in the tray / menu bar",
                                  variable=self.v_tray))
        self.v_upd = tk.BooleanVar(value=cfg.get("check_updates", True))
        f.add("", ttk.Checkbutton(f, text="Check for updates daily", variable=self.v_upd))
        self.v_theme = tk.StringVar(value=cfg.get("theme", "light"))
        f.add("Theme", ttk.Combobox(f, textvariable=self.v_theme, values=["light", "dark", "system"],
                                    state="readonly", width=10))
        self.v_level = tk.StringVar(value=cfg.get("log_level", "INFO"))
        f.add("Log level", ttk.Combobox(f, textvariable=self.v_level, values=["DEBUG", "INFO", "WARNING", "ERROR"],
                                        state="readonly", width=10))
        self.v_ret = tk.StringVar(value=str(cfg.get("retention_days", 0)))
        f.add("Keep data (days)", ttk.Entry(f, textvariable=self.v_ret, width=8),
              hint="0 keeps everything. Undelivered results are never purged.")
        f.section("Order queries (instrument asks the host for a worklist)")
        orders = cfg.get("orders") or {}
        self.v_oprov = tk.StringVar(value=orders.get("provider", "none"))
        f.add("Source", ttk.Combobox(f, textvariable=self.v_oprov, values=["none", "http"], state="readonly", width=8),
              hint="none: answer 'no orders'. http: look orders up from your LIS/EMR (see the README for the contract).")
        self.v_ourl = tk.StringVar(value=orders.get("url", ""))
        f.add("Lookup URL", ttk.Entry(f, textvariable=self.v_ourl))
        oauth = orders.get("auth") or {}
        self.v_okey = tk.StringVar(value=oauth.get("api_key", ""))
        f.add("API key", ttk.Entry(f, textvariable=self.v_okey, show="•"))
        if not keyring_available:
            ttk.Label(f, text="No OS credential store was found; secrets are kept in the config file (owner-only).",
                      style="Hint.TLabel").grid(row=99, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        self.finish_layout()

    def collect(self) -> dict[str, Any]:
        c = self.cfg
        try:
            ret = int(self.v_ret.get() or 0)
        except ValueError as exc:
            raise ValueError("Days must be a whole number.") from exc
        if not self.v_inst.get().strip():
            raise ValueError("Instance ID cannot be empty.")
        c.update(app_name=self.v_app.get().strip() or "LabSync", instance_id=self.v_inst.get().strip(),
                 auto_start=bool(self.v_auto.get()), start_minimized=bool(self.v_min.get()),
                 minimize_to_tray=bool(self.v_tray.get()), check_updates=bool(self.v_upd.get()),
                 theme=self.v_theme.get(), log_level=self.v_level.get(), retention_days=ret)
        c["orders"] = {"provider": self.v_oprov.get(), "url": self.v_ourl.get().strip(), "timeout": 10,
                       "auth": {"method": "api_key", "header": "X-API-Key", "api_key": self.v_okey.get()}
                       if self.v_okey.get() else {"method": "none"}}
        if c["orders"]["provider"] == "http" and not c["orders"]["url"].startswith(("http://", "https://")):
            raise ValueError("Order lookup URL must start with http:// or https://")
        return c
