"""Look and feel: light and dark palettes, soft rounded surfaces and the window chrome.

Built on the Sun Valley ttk theme (sv-ttk) for inputs, buttons and lists, with
LabSync's own surfaces on top:

- ``Card.TFrame``: a rounded panel with a hairline border, a faint top
  highlight and a soft shadow (drawn with Pillow, antialiased, used as a
  nine-slice image so it stretches to any size).
- ``Nav.TButton``: sidebar items with a rounded selected/hover state.
- ``Pill*.TLabel``: small rounded status chips (ok, warn, danger, neutral).
- On Windows 11 the title bar follows the theme (dark title bar, matching
  caption colour, rounded window corners).

``apply(root, mode)`` can be called again at any time to switch modes; every
registered callback (``on_change``) then re-colours what isn't a ttk style.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from tkinter import ttk

log = logging.getLogger("labsync.gui.theme")

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f2f4f8", "sidebar": "#e9edf4", "surface": "#ffffff", "surface2": "#f6f8fb", "border": "#e1e5ee",
        "text": "#171a23", "muted": "#5f6b7d", "faint": "#9aa3b2", "accent": "#005fb8", "accent_text": "#ffffff",
        "accent_soft": "#dbe8f7", "hover": "#dfe4ee", "ok": "#15803d", "ok_soft": "#dcf3e4", "warn": "#a15c07",
        "warn_soft": "#fbecd3", "danger": "#c42b1c", "danger_soft": "#fbe1de", "neutral_soft": "#e7eaf1",
        "shadow": "#1b2a4a", "sheen": "#ffffff",
    },
    "dark": {
        "bg": "#14161b", "sidebar": "#1a1d24", "surface": "#20242c", "surface2": "#262a33", "border": "#2e3441",
        "text": "#e9ecf2", "muted": "#a3acbb", "faint": "#6f7889", "accent": "#57c8ff", "accent_text": "#0b1a24",
        "accent_soft": "#1f3a4d", "hover": "#262b35", "ok": "#4ade80", "ok_soft": "#173826", "warn": "#fbbf24",
        "warn_soft": "#3d3115", "danger": "#ff8a80", "danger_soft": "#43211f", "neutral_soft": "#2b303b",
        "shadow": "#000000", "sheen": "#ffffff",
    },
}

RADIUS = 12
SHADOW = 6  # px of soft shadow around cards
CARD_PAD = SHADOW + 12  # pass as padding= to a Card.TFrame

_state: dict = {"mode": "light", "images": {}, "created": set(), "callbacks": []}


def palette() -> dict[str, str]:
    return PALETTES[_state["mode"]]


def color(name: str) -> str:
    return palette()[name]


def mode() -> str:
    return _state["mode"]


def on_change(callback: Callable[[], None]) -> None:
    _state["callbacks"].append(callback)


# ---------------------------------------------------------------------------- system mode


def system_prefers_dark() -> bool:
    try:
        import darkdetect  # optional

        return bool(darkdetect.isDark())
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True,
                                 timeout=2)
            return "dark" in out.stdout.lower()
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=2)
        return "dark" in out.stdout.lower()
    except Exception:
        return False


def resolve(requested: str) -> str:
    if requested == "dark":
        return "dark"
    if requested == "light":
        return "light"
    return "dark" if system_prefers_dark() else "light"


# ---------------------------------------------------------------------------- drawing


def _rgba(hex_color: str, alpha: float) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(round(alpha * 255))


def _rounded(fill: str, outline: str | None, radius: int, size: tuple[int, int], under: str, shadow: int = 0,
             shadow_color: str = "#000000", shadow_alpha: float = 0.0, sheen: str | None = None,
             sheen_alpha: float = 0.0, scale: int = 3):
    """A rounded rectangle (optionally with a soft drop shadow and a top highlight), antialiased and
    drawn over ``under`` (the colour of what it sits on), so no corner pixels are left transparent."""
    from PIL import Image, ImageDraw, ImageFilter, ImageTk

    w, h = size
    W, H, R, S = w * scale, h * scale, radius * scale, shadow * scale
    img = Image.new("RGBA", (W, H), _rgba(under, 1))
    if shadow and shadow_alpha:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((S, S + scale * 2, W - S - 1, H - S - 1 + scale), R,
                                             fill=_rgba(shadow_color, shadow_alpha))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(S / 2.2)))
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    box = (S, S, W - S - 1, H - S - 1)
    d.rounded_rectangle(box, R, fill=_rgba(fill, 1), outline=_rgba(outline, 1) if outline else None,
                        width=scale if outline else 0)
    if sheen and sheen_alpha:
        # a faint highlight along the top edge, like light catching glass
        d.rounded_rectangle((S + scale, S + scale, W - S - 1 - scale, S + R), R - scale, outline=None,
                            fill=None)
        d.line((S + R, S + scale, W - S - 1 - R, S + scale), fill=_rgba(sheen, sheen_alpha), width=scale)
    img = Image.alpha_composite(img, card)
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))


def _heading(fill: str, line: str):
    from PIL import Image, ImageDraw, ImageTk

    img = Image.new("RGBA", (8, 8), _rgba(fill, 1))
    ImageDraw.Draw(img).line((0, 7, 8, 7), fill=_rgba(line, 1))
    return ImageTk.PhotoImage(img)


def _element(style: ttk.Style, name: str, images: list, border: int | tuple, **kw) -> str:
    """Create an image element once per ttk theme; returns its name."""
    theme = style.theme_use()
    key = (theme, name)
    if key not in _state["created"]:
        style.element_create(name, "image", *images, border=border, sticky="nsew", **kw)
        _state["created"].add(key)
    return name


def _keep(key: str, factory):
    """Images are cached per mode so switching back and forth doesn't redraw them."""
    full = f"{_state['mode']}:{key}"
    if full not in _state["images"]:
        _state["images"][full] = factory()
    return _state["images"][full]


# ---------------------------------------------------------------------------- fonts


def _fonts(root: tk.Misc) -> dict[str, tuple]:
    families = set(tkfont.families(root))
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Inter", "Cantarell", "Noto Sans",
                      "DejaVu Sans"):
        if candidate in families:
            family = candidate
            break
    else:
        family = tkfont.nametofont("TkDefaultFont").actual("family")
    display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else family
    return {
        "body": (family, 10), "small": (family, 9), "strong": (family, 10, "bold"), "section": (family, 11, "bold"),
        "title": (display, 18, "bold"), "big": (display, 22, "bold"), "brand": (display, 13, "bold"),
        "mono": ("Cascadia Mono" if "Cascadia Mono" in families else "TkFixedFont", 9),
    }


FONTS: dict[str, tuple] = {}


# ---------------------------------------------------------------------------- apply


def apply(root: tk.Tk, requested: str = "system") -> str:
    """Switch to light, dark or the system's mode. Returns the mode in use."""
    _state["mode"] = resolve(requested)
    p = palette()
    try:
        import sv_ttk

        sv_ttk.set_theme(_state["mode"], root)
    except Exception:
        style = ttk.Style(root)
        for candidate in ("vista", "aqua", "clam"):
            if candidate in style.theme_names():
                style.theme_use(candidate)
                break
    # sv-ttk recolours on <<ThemeChanged>> (an event) and also writes its colours into the option
    # database (tk_setPalette), which ttk labels would take as their own -background/-foreground.
    # Let that run first, then put our colours on top and hand label colours back to the styles.
    try:
        root.update()
        # From here on, our own styles are the source of truth: stop sv-ttk from re-running its palette
        # (it would recolour every label each time a style changes)
        root.tk.call("bind", root.winfo_class(), "<<ThemeChanged>>", "")
    except tk.TclError:
        pass
    FONTS.update(_fonts(root))
    style = ttk.Style(root)
    root.configure(background=p["bg"])
    root.option_clear()  # drop tk_setPalette's entries; ttk widgets take colours from their styles
    root.option_add("*Menu.background", p["surface"], "interactive")
    root.option_add("*Menu.foreground", p["text"], "interactive")
    root.option_add("*Menu.activeBackground", p["accent_soft"], "interactive")
    root.option_add("*Menu.activeForeground", p["text"], "interactive")
    root.option_add("*Menu.borderWidth", 0, "interactive")
    root.option_add("*Text.background", p["surface"], "interactive")
    root.option_add("*Text.foreground", p["text"], "interactive")
    root.option_add("*Listbox.background", p["surface"], "interactive")
    root.option_add("*Listbox.foreground", p["text"], "interactive")
    _reset_labels(root)

    style.configure(".", font=FONTS["body"], background=p["bg"], foreground=p["text"], troughcolor=p["bg"],
                    fieldbackground=p["surface"], borderwidth=0, relief="flat", focuscolor=p["accent"],
                    selectbackground=p["accent_soft"], selectforeground=p["text"], insertcolor=p["text"])
    style.map(".", foreground=[("disabled", p["faint"])])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("TCheckbutton", background=p["bg"])
    style.configure("TRadiobutton", background=p["bg"])
    style.configure("Hint.TLabel", foreground=p["muted"], background=p["bg"], font=FONTS["small"])
    style.configure("Section.TLabel", font=FONTS["section"], background=p["bg"])
    style.configure("Value.TLabel", font=FONTS["strong"], background=p["bg"])
    style.configure("Title.TLabel", font=FONTS["title"], background=p["bg"], foreground=p["text"])
    style.configure("Subtitle.TLabel", font=FONTS["body"], background=p["bg"], foreground=p["muted"])

    # Cards
    # Tk tiles (doesn't stretch) the edges of an image element, so the corners must sit well inside
    # the border: a big image with a generous border keeps the soft shadow from repeating
    card = _keep("card", lambda: _rounded(p["surface"], p["border"], RADIUS, (96, 96), p["bg"], shadow=SHADOW,
                                          shadow_color=p["shadow"], shadow_alpha=0.10 if mode() == "light" else 0.30))
    el = _element(style, "Card.bg", [card], border=SHADOW + RADIUS + 12)
    style.layout("Card.TFrame", [(el, {"sticky": "nsew"})])
    style.configure("Card.TFrame", padding=CARD_PAD, background=p["bg"])
    for name, font, fg in (("Card.TLabel", FONTS["body"], p["text"]), ("CardHint.TLabel", FONTS["small"], p["muted"]),
                           ("CardBig.TLabel", FONTS["big"], p["text"]),
                           ("CardSection.TLabel", FONTS["section"], p["text"])):
        style.configure(name, background=p["surface"], foreground=fg, font=font)
    style.configure("Card.TCheckbutton", background=p["surface"])
    style.configure("Inner.TFrame", background=p["surface"])

    # Lists sit flush on cards: no field border, flat headings with a hairline underneath
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nsew"})])
    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                    rowheight=30, borderwidth=0, relief="flat")
    style.map("Treeview", background=[("selected", p["accent_soft"])], foreground=[("selected", p["text"])])
    head = _keep("heading", lambda: _heading(p["surface"], p["border"]))
    head_hover = _keep("heading-hover", lambda: _heading(p["surface2"], p["border"]))
    el = _element(style, "FlatHeading.bg", [head, ("active", head_hover)], border=(2, 2, 2, 3))
    style.layout("Treeview.Heading", [(el, {"sticky": "nsew", "children": [
        ("Treeheading.padding", {"sticky": "nsew", "children": [
            ("Treeheading.image", {"side": "right", "sticky": ""}),
            ("Treeheading.text", {"sticky": "we"})]})]})])
    style.configure("Treeview.Heading", font=FONTS["small"], foreground=p["muted"], padding=(10, 7),
                    background=p["surface"])
    style.map("Treeview.Heading", foreground=[("active", p["text"])], background=[("active", p["surface2"])])

    # Sidebar and navigation
    style.configure("Sidebar.TFrame", background=p["sidebar"])
    style.configure("Sidebar.TLabel", background=p["sidebar"], foreground=p["text"])
    style.configure("SidebarHint.TLabel", background=p["sidebar"], foreground=p["muted"], font=FONTS["small"])
    style.configure("Brand.TLabel", background=p["sidebar"], foreground=p["text"], font=FONTS["brand"])
    nav_normal = _keep("nav0", lambda: _rounded(p["sidebar"], None, 9, (40, 36), p["sidebar"]))
    nav_hover = _keep("nav1", lambda: _rounded(p["hover"], None, 9, (40, 36), p["sidebar"]))
    nav_sel = _keep("nav2", lambda: _rounded(p["accent_soft"], None, 9, (40, 36), p["sidebar"]))
    el = _element(style, "Nav.bg", [nav_normal, ("selected", nav_sel), ("active", nav_hover)], border=10)
    style.layout("Nav.TButton", [(el, {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "w"})]})]})])
    style.configure("Nav.TButton", padding=(12, 8), anchor="w", foreground=p["text"], font=FONTS["body"],
                    background=p["sidebar"])
    style.map("Nav.TButton", foreground=[("selected", p["text"])])

    # Status chips: Pill* sit on the sidebar, CardPill* on cards
    for name, bg, fg in (("PillOk", p["ok_soft"], p["ok"]), ("PillWarn", p["warn_soft"], p["warn"]),
                         ("PillDanger", p["danger_soft"], p["danger"]), ("PillNeutral", p["neutral_soft"], p["muted"]),
                         ("PillAccent", p["accent_soft"], p["text"])):
        for prefix, under in (("", p["sidebar"]), ("Card", p["surface"])):
            img = _keep(prefix + name, lambda bg=bg, under=under: _rounded(bg, None, 10, (28, 22), under))
            el = _element(style, f"{prefix}{name}.bg", [img], border=10)
            style.layout(f"{prefix}{name}.TLabel", [(el, {"sticky": "nsew", "children": [
                ("Label.padding", {"sticky": "nsew", "children": [("Label.label", {"sticky": "nsew"})]})]})])
            style.configure(f"{prefix}{name}.TLabel", padding=(10, 4), foreground=fg, font=FONTS["small"],
                            background=under)

    for cb in list(_state["callbacks"]):
        try:
            cb()
        except tk.TclError:
            pass
        except Exception:
            log.exception("theme change callback failed")
    window_chrome(root)
    return _state["mode"]


def _reset_labels(widget: tk.Misc) -> None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            try:
                child.configure(background="", foreground="")
            except tk.TclError:
                pass
        _reset_labels(child)


def window_chrome(window: tk.Misc) -> None:
    """Windows 11: title bar in the app's colours with rounded corners. No-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        dwm = ctypes.windll.dwmapi

        def set_attr(attr: int, value: int) -> None:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_color: str) -> int:
            r, g, b, _ = _rgba(hex_color, 1)
            return r | (g << 8) | (b << 16)

        p = palette()
        set_attr(20, 1 if mode() == "dark" else 0)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_attr(33, 2)  # DWMWA_WINDOW_CORNER_PREFERENCE = round
        set_attr(34, colorref(p["border"]))  # DWMWA_BORDER_COLOR
        set_attr(35, colorref(p["bg"]))  # DWMWA_CAPTION_COLOR
        set_attr(36, colorref(p["text"]))  # DWMWA_TEXT_COLOR
    except Exception:  # older Windows: keep the default title bar
        log.debug("window chrome not applied", exc_info=True)


# ---------------------------------------------------------------------------- icons


def icon(name: str, size: int = 18, tone: str = "muted"):
    """Small line icons for the sidebar, drawn so they work with any font and in both modes."""
    return _keep(f"icon:{name}:{size}:{tone}", lambda: _draw_icon(name, size, color(tone)))


def _draw_icon(name: str, size: int, hex_color: str):
    from PIL import Image, ImageDraw, ImageTk

    s = 4
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = _rgba(hex_color, 1)
    w = max(2, int(1.7 * s))
    m = n // 8
    if name == "instruments":  # flask
        neck = n * 0.38, n * 0.62
        d.line((neck[0], m, neck[0], n * 0.42), fill=c, width=w)
        d.line((neck[1], m, neck[1], n * 0.42), fill=c, width=w)
        d.line((neck[0] - s * 2, m, neck[1] + s * 2, m), fill=c, width=w)
        d.line((neck[0], n * 0.42, m, n - m), fill=c, width=w)
        d.line((neck[1], n * 0.42, n - m, n - m), fill=c, width=w)
        d.line((m, n - m, n - m, n - m), fill=c, width=w)
        d.line((n * 0.27, n * 0.68, n * 0.73, n * 0.68), fill=c, width=w)
    elif name == "imaging":  # scan frame with a circle
        L = n * 0.28
        for x0, y0, dx, dy in ((m, m, 1, 1), (n - m, m, -1, 1), (m, n - m, 1, -1), (n - m, n - m, -1, -1)):
            d.line((x0, y0, x0 + dx * L, y0), fill=c, width=w)
            d.line((x0, y0, x0, y0 + dy * L), fill=c, width=w)
        r = n * 0.18
        d.ellipse((n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r), outline=c, width=w)
    elif name == "results":  # list
        for i, y in enumerate((0.27, 0.5, 0.73)):
            d.ellipse((m, n * y - s * 1.6, m + s * 3.2, n * y + s * 1.6), fill=c)
            d.line((m + s * 6, n * y, n - m, n * y), fill=c, width=w)
            del i
    elif name == "delivery":  # paper plane
        d.line((m, n * 0.45, n - m, m), fill=c, width=w)
        d.line((n - m, m, n * 0.6, n - m), fill=c, width=w)
        d.line((n * 0.6, n - m, n * 0.45, n * 0.55), fill=c, width=w)
        d.line((n * 0.45, n * 0.55, m, n * 0.45), fill=c, width=w)
        d.line((n * 0.45, n * 0.55, n - m, m), fill=c, width=w)
    elif name == "messages":  # speech bubble
        d.rounded_rectangle((m, m + s, n - m, n * 0.7), radius=s * 4, outline=c, width=w)
        d.line((n * 0.3, n * 0.7, n * 0.24, n - m), fill=c, width=w)
        d.line((n * 0.24, n - m, n * 0.45, n * 0.7), fill=c, width=w)
    elif name == "log":  # terminal
        d.rounded_rectangle((m, m + s, n - m, n - m - s), radius=s * 3, outline=c, width=w)
        d.line((n * 0.27, n * 0.4, n * 0.4, n * 0.52), fill=c, width=w)
        d.line((n * 0.4, n * 0.52, n * 0.27, n * 0.64), fill=c, width=w)
        d.line((n * 0.48, n * 0.66, n * 0.7, n * 0.66), fill=c, width=w)
    elif name == "settings":  # sliders
        for y, x in ((0.3, 0.62), (0.7, 0.38)):
            d.line((m, n * y, n - m, n * y), fill=c, width=w)
            r = s * 3.4
            d.ellipse((n * x - r, n * y - r, n * x + r, n * y + r), fill=(0, 0, 0, 0), outline=c, width=w)
    elif name == "sun":
        r = n * 0.2
        d.ellipse((n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r), outline=c, width=w)
        import math

        for k in range(8):
            a = k * math.pi / 4
            r1, r2 = n * 0.32, n * 0.44
            d.line((n / 2 + r1 * math.cos(a), n / 2 + r1 * math.sin(a), n / 2 + r2 * math.cos(a),
                    n / 2 + r2 * math.sin(a)), fill=c, width=w)
    elif name == "moon":
        d.ellipse((m, m, n - m, n - m), fill=c)
        d.ellipse((m + n * 0.28, m - n * 0.08, n - m + n * 0.28, n - m - n * 0.08), fill=(0, 0, 0, 0))
    elif name == "more":
        for x in (0.25, 0.5, 0.75):
            r = s * 2
            d.ellipse((n * x - r, n / 2 - r, n * x + r, n / 2 + r), fill=c)
    elif name == "dot":
        r = n * 0.22
        d.ellipse((n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r), fill=c)
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
