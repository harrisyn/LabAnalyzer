"""Read-only windows: result detail and raw message viewer."""

from __future__ import annotations

import io
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk
from typing import Any

from ..models import Report, escape_control
from .common import PAD, center_on, local_ts, make_tree


def _raw_text_widget(parent: tk.Misc, raw: bytes) -> tk.Frame:
    frame = ttk.Frame(parent)
    bar = ttk.Frame(frame)
    bar.pack(fill="x", pady=(0, 4))
    mode = tk.StringVar(value="text")
    text = tk.Text(frame, wrap="none", font=("TkFixedFont", 10), height=20)
    ys = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

    def render() -> None:
        text.configure(state="normal")
        text.delete("1.0", "end")
        if mode.get() == "hex":
            lines = []
            for i in range(0, len(raw), 16):
                chunk = raw[i : i + 16]
                hexpart = " ".join(f"{b:02X}" for b in chunk)
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                lines.append(f"{i:08X}  {hexpart:<48}  {asc}")
            text.insert("1.0", "\n".join(lines))
        else:
            text.insert("1.0", escape_control(raw))
        text.configure(state="disabled")

    ttk.Radiobutton(bar, text="Text", value="text", variable=mode, command=render).pack(side="left")
    ttk.Radiobutton(bar, text="Hex", value="hex", variable=mode, command=render).pack(side="left", padx=PAD)

    def save() -> None:
        path = filedialog.asksaveasfilename(parent=frame, defaultextension=".bin",
                                            filetypes=[("Capture", "*.bin"), ("All files", "*")])
        if path:
            with open(path, "wb") as fh:
                fh.write(raw)

    ttk.Button(bar, text="Save capture…", command=save).pack(side="right")
    ttk.Label(bar, text=f"{len(raw)} bytes", style="Hint.TLabel").pack(side="right", padx=PAD)
    ys.pack(side="right", fill="y")
    xs.pack(side="bottom", fill="x")
    text.pack(fill="both", expand=True)
    render()
    return frame


class RawMessageWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str, raw: bytes):
        super().__init__(parent)
        self.title(title)
        self.geometry("900x560")
        _raw_text_widget(self, raw).pack(fill="both", expand=True, padx=PAD, pady=PAD)
        center_on(self, parent)


class ReportWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, report: Report, meta: dict[str, Any], raw: bytes,
                 delivery: list[Any], destinations: dict[str, str], on_resend: Callable[[str], None]):
        super().__init__(parent)
        self.title(f"Specimen {report.specimen.id or '—'}")
        self.geometry("980x640")
        self._images: list[Any] = []
        top = ttk.Frame(self, padding=PAD)
        top.pack(fill="x")
        p, s = report.patient, report.specimen
        facts = [
            ("Specimen", s.id or "—"), ("Patient ID", p.id or "—"), ("Name", p.name.full or "—"),
            ("Birth date", p.birth_date or "—"), ("Sex", p.sex or "—"), ("Instrument", meta.get("device", "")),
            ("Received", local_ts(meta.get("received_at"))), ("Type", "QC" if report.is_qc else "Patient"),
        ]
        for i, (k, v) in enumerate(facts):
            ttk.Label(top, text=k, style="Hint.TLabel").grid(row=i // 4 * 2, column=i % 4, sticky="w", padx=(0, 24))
            ttk.Label(top, text=v, style="Value.TLabel").grid(row=i // 4 * 2 + 1, column=i % 4, sticky="w", padx=(0, 24))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        res = ttk.Frame(nb, padding=4)
        nb.add(res, text=f"Results ({len(report.observations)})")
        tree = make_tree(res, [("seq", "#", 40), ("code", "Test", 110), ("name", "Name", 140), ("value", "Value", 110),
                               ("units", "Units", 90), ("ref", "Reference", 110), ("flags", "Flags", 70),
                               ("status", "Status", 60), ("time", "Measured", 150), ("notes", "Notes", 200)])
        tree.tag_configure("abnormal", foreground="#b3261e")
        for i, o in enumerate(report.observations):
            tree.insert("", "end", iid=str(i), values=(
                o.sequence, o.code, o.name, o.value, o.units, o.reference_range, " ".join(o.flags), o.status,
                local_ts(o.observed_at), "; ".join(o.comments)), tags=("abnormal",) if o.abnormal else ())

        if report.attachments:
            att = ttk.Frame(nb, padding=4)
            nb.add(att, text=f"Images ({len(report.attachments)})")
            canvas = tk.Canvas(att, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            x = 8
            try:
                from PIL import Image, ImageTk

                for a in report.attachments:
                    try:
                        img = Image.open(io.BytesIO(a.data))
                        img.thumbnail((360, 360))
                        photo = ImageTk.PhotoImage(img)
                    except Exception:
                        continue
                    self._images.append(photo)
                    canvas.create_image(x, 24, image=photo, anchor="nw")
                    canvas.create_text(x, 6, text=a.name, anchor="nw")
                    x += photo.width() + 16
            except ImportError:
                ttk.Label(att, text="Install Pillow to view images.").pack()

        dl = ttk.Frame(nb, padding=4)
        nb.add(dl, text="Delivery")
        dtree = make_tree(dl, [("dest", "Destination", 200), ("status", "Status", 90), ("attempts", "Attempts", 70),
                               ("sent", "Sent", 150), ("code", "HTTP", 60), ("error", "Last error", 380)], height=6)
        for row in delivery:
            dtree.insert("", "end", values=(destinations.get(row["destination_id"], row["destination_id"]), row["status"],
                                            row["attempts"], local_ts(row["sent_at"]), row["response_code"] or "",
                                            row["last_error"] or ""))
        bar = ttk.Frame(dl)
        bar.grid(row=2, column=0, sticky="w", pady=(PAD, 0))
        if destinations:
            v = tk.StringVar(value=next(iter(destinations.values())))
            ttk.Combobox(bar, textvariable=v, values=list(destinations.values()), state="readonly", width=30).pack(side="left")

            def resend() -> None:
                for did, name in destinations.items():
                    if name == v.get():
                        on_resend(did)
                        self.destroy()
                        return

            ttk.Button(bar, text="Send again", command=resend).pack(side="left", padx=PAD)

        rawf = ttk.Frame(nb, padding=4)
        nb.add(rawf, text="Raw message")
        _raw_text_widget(rawf, raw).pack(fill="both", expand=True)
        if report.comments:
            cf = ttk.Frame(nb, padding=4)
            nb.add(cf, text="Comments")
            t = tk.Text(cf, wrap="word", height=10)
            t.insert("1.0", "\n".join(report.comments))
            t.configure(state="disabled")
            t.pack(fill="both", expand=True)
        center_on(self, parent)
