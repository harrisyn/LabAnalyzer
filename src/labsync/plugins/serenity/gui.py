"""Settings > Integrations panel for the Serenity plugin."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ...gui.common import Form
from .link import NAME, apply_setup_code, check_url, is_configured


class SerenityPanel(Form):
    def __init__(self, parent: tk.Misc, settings: dict[str, Any]):
        super().__init__(parent)
        self.settings = dict(settings)
        paired = is_configured(settings)
        self.add("Status", ttk.Label(self, style="Hint.TLabel", wraplength=420, justify="left", text=(
            f"Paired as {settings.get('device_name') or 'this computer'} for "
            f"{settings.get('organization') or 'your organisation'}." if paired else
            f"Not paired. In {NAME} open Devices, register this computer and paste its setup code here.")))
        self.v_code = tk.StringVar()
        self.add("Setup code", ttk.Entry(self, textvariable=self.v_code, show="•"),
                 hint=f"SRN1.… from {NAME}'s Devices screen. Pasting a new code replaces the current key.")
        self.v_url = tk.StringVar(value=settings.get("url", ""))
        self.add("Address", ttk.Entry(self, textvariable=self.v_url),
                 hint="Filled from the setup code. Change it only to point at another environment.")
        self.v_ca = tk.StringVar(value=settings.get("ca_bundle", ""))
        self.add("Extra CA file", ttk.Entry(self, textvariable=self.v_ca),
                 hint="Optional PEM file when a proxy inspects HTTPS traffic.")
        self.v_forget = tk.BooleanVar(value=False)
        if paired:
            self.add("", ttk.Checkbutton(self, text="Unpair (forget the device key)", variable=self.v_forget))

    def collect(self) -> dict[str, Any]:
        s = dict(self.settings)
        if self.v_forget.get():
            s.update(url="", device_key="", device_id="", device_name="", organization="")
        elif self.v_code.get().strip():
            s = apply_setup_code(s, self.v_code.get())
        elif self.v_url.get().strip() != s.get("url", ""):
            s["url"] = check_url(self.v_url.get()) if self.v_url.get().strip() else ""
        s["ca_bundle"] = self.v_ca.get().strip()
        return s
