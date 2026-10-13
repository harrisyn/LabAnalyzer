"""System tray icon (Windows). macOS keeps the Dock icon instead (pystray and Tk cannot
share the macOS main thread), and Linux desktops vary too much to rely on a tray."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

log = logging.getLogger("labsync.gui")


class Tray:
    def __init__(self, icon_path: str, title: str, on_show: Callable[[], None], on_quit: Callable[[], None]):
        self.icon = None
        self.available = False
        if sys.platform != "win32":
            return
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return
        try:
            image = Image.open(icon_path)
            menu = pystray.Menu(pystray.MenuItem("Open LabSync", lambda *_: on_show(), default=True),
                                pystray.MenuItem("Quit", lambda *_: on_quit()))
            self.icon = pystray.Icon("LabSync", image, title, menu)
            threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
            self.available = True
        except Exception as exc:  # no tray on this desktop
            log.info("system tray unavailable: %s", exc)
            self.icon = None

    def notify(self, message: str, title: str = "LabSync") -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
