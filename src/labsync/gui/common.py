"""Shared Tk helpers."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

PAD = 8


def local_ts(iso: str | None, with_seconds: bool = True) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M")


def make_tree(parent: tk.Misc, columns: list[tuple[str, str, int]], height: int = 12,
              selectmode: str = "extended") -> ttk.Treeview:
    """Treeview with scrollbars inside ``parent`` (which should be an empty frame)."""
    tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", height=height,
                        selectmode=selectmode)
    for key, title, width in columns:
        tree.heading(key, text=title, command=lambda k=key: sort_tree(tree, k, False))
        tree.column(key, width=width, minwidth=40, stretch=width >= 150, anchor="w")
    ys = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    xs = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    return tree


def sort_tree(tree: ttk.Treeview, col: str, reverse: bool) -> None:
    rows = [(tree.set(k, col), k) for k in tree.get_children("")]

    def key(item: tuple[str, str]):
        v = item[0]
        try:
            return (0, float(v))
        except ValueError:
            return (1, v.lower())

    rows.sort(key=key, reverse=reverse)
    for i, (_, k) in enumerate(rows):
        tree.move(k, "", i)
    tree.heading(col, command=lambda: sort_tree(tree, col, not reverse))


def replace_rows(tree: ttk.Treeview, rows: list[tuple[str, tuple, tuple[str, ...]]]) -> None:
    """Replace tree content while keeping the selection and scroll position."""
    selected = set(tree.selection())
    first = tree.yview()[0]
    tree.delete(*tree.get_children(""))
    for iid, values, tags in rows:
        tree.insert("", "end", iid=iid, values=values, tags=tags)
    keep = [i for i in selected if tree.exists(i)]
    if keep:
        tree.selection_set(keep)
    tree.yview_moveto(first)


class Form(ttk.Frame):
    """Two-column label/field grid."""

    def __init__(self, parent: tk.Misc, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(1, weight=1)
        self._row = 0
        self.rows: dict[str, list[tk.Widget]] = {}

    def add(self, label: str, widget: tk.Widget, key: str | None = None, hint: str = "") -> tk.Widget:
        lbl = ttk.Label(self, text=label)
        lbl.grid(row=self._row, column=0, sticky="w", padx=(0, PAD), pady=3)
        widget.grid(row=self._row, column=1, sticky="ew", pady=3)
        items: list[tk.Widget] = [lbl, widget]
        if hint:
            h = ttk.Label(self, text=hint, style="Hint.TLabel", wraplength=420, justify="left")
            self._row += 1
            h.grid(row=self._row, column=1, sticky="w", pady=(0, 4))
            items.append(h)
        self.rows[key or label] = items
        self._row += 1
        return widget

    def section(self, title: str) -> None:
        lbl = ttk.Label(self, text=title, style="Section.TLabel")
        lbl.grid(row=self._row, column=0, columnspan=2, sticky="w", pady=(PAD, 2))
        self._row += 1

    def show(self, key: str, visible: bool) -> None:
        for w in self.rows.get(key, []):
            if visible:
                w.grid()
            else:
                w.grid_remove()


def center_on(window: tk.Toplevel, parent: tk.Misc) -> None:
    window.update_idletasks()
    w, h = window.winfo_reqwidth(), window.winfo_reqheight()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except tk.TclError:
        px = py = 0
        pw, ph = window.winfo_screenwidth(), window.winfo_screenheight()
    x = max(0, px + (pw - w) // 2)
    y = max(0, py + (ph - h) // 3)
    window.geometry(f"+{x}+{y}")
