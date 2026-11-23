"""Wires the imaging module together: settings view, receiver, forwarder and disk clean-up.

Settings come from two places:
- the ``imaging`` section of LabSync's configuration (what people set in the
  app), plus the settings of plugins that own an imaging destination, and
- runtime state kept next to the queue (``state.json``): the imaging devices
  a plugin's platform last said may send through this computer
  (``remote_nodes``, per plugin), so the list survives a restart offline.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .. import plugins
from ..config import default_imaging
from .destinations import make_destination
from .forwarder import Forwarder
from .receiver import Receiver
from .store import Store

log = logging.getLogger("labsync.imaging")

CLEANUP_SECONDS = 600
RUNTIME_KEYS = ("remote_nodes",)
LISTEN_KEYS = ("enabled", "ae_title", "port", "bind_address")


class ImagingSettings:
    """The ``config.get(key)`` view the receiver, forwarder and destinations expect."""

    def __init__(self, cfg: dict[str, Any], state_path: Path):
        self._lock = threading.RLock()
        self._cfg = copy.deepcopy(cfg)
        self.state_path = Path(state_path)
        self._state: dict[str, Any] = {"remote_nodes": {}}
        if self.state_path.exists():
            try:
                stored = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(stored.get("serenity_nodes"), list):  # written by the first imaging build
                    stored.setdefault("remote_nodes", {})["serenity"] = stored["serenity_nodes"]
                self._state.update({k: v for k, v in stored.items() if k in RUNTIME_KEYS})
            except (OSError, ValueError):
                log.warning("imaging state file unreadable; starting with no remotely managed devices")

    def replace_config(self, cfg: dict[str, Any]) -> None:
        with self._lock:
            self._cfg = copy.deepcopy(cfg)

    def get(self, key: str) -> Any:
        with self._lock:
            if key in RUNTIME_KEYS:
                return copy.deepcopy(self._state.get(key))
            imaging = {**default_imaging(), **(self._cfg.get("imaging") or {})}
            return copy.deepcopy(imaging.get(key))

    def full_config(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._cfg)

    def update(self, **values: Any) -> None:
        unknown = set(values) - set(RUNTIME_KEYS)
        if unknown:
            raise KeyError(f"not a runtime setting: {', '.join(sorted(unknown))}")
        with self._lock:
            self._state.update(copy.deepcopy(values))
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)


class ImagingService:
    def __init__(self, cfg: dict[str, Any], home: Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings = ImagingSettings(cfg, self.home / "state.json")
        self.store = Store(self.home / "imaging.db")
        self._dest_cache: dict[str, tuple[str, Any]] = {}
        self.receiver = Receiver(self.settings, self.store, self.home / "images", self.destination_ids,
                                 on_received=self._on_received)
        self.forwarder = Forwarder(self.store, self.settings, self.destinations)
        self.running = False
        self._stop = threading.Event()
        self._cleanup: threading.Thread | None = None
        self.on_change = None  # set by the engine: called when something worth showing happened

    # ------------------------------------------------------------------ destinations
    def destinations(self) -> list:
        """Destinations to send to now: enabled ones whose type is built in or owned by an enabled plugin.
        Objects are reused while their settings are unchanged, so HTTP sessions are kept."""
        cfg = self.settings.full_config()
        dests = []
        cache: dict[str, tuple[Any, Any]] = {}
        for spec in self.settings.get("destinations") or []:
            if not spec.get("enabled", True) or not spec.get("id"):
                continue
            owner = plugins.imaging_destination_owner(cfg, spec.get("type", ""))
            key = json.dumps([spec, owner[1] if owner else None], sort_keys=True, default=str)
            prev = self._dest_cache.get(spec["id"])
            if prev and prev[0] == key:
                dest = prev[1]
            else:
                dest = make_destination(spec, self.settings, lambda t, o=owner: o)
            if dest is not None:
                cache[spec["id"]] = (key, dest)
                dests.append(dest)
        self._dest_cache = cache
        return dests

    def destination_ids(self) -> list[str]:
        return [d.id for d in self.destinations()]

    def _on_received(self) -> None:
        self.forwarder.nudge()
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------------ lifecycle (blocking; run off the event loop)
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self.store.log_event("info", "Imaging module started")
        recovered = self.receiver.reconcile()
        if recovered:
            log.warning("re-queued %d image(s) found on disk after a restart", recovered)
        self.receiver.start()
        self.forwarder = Forwarder(self.store, self.settings, self.destinations)
        self.forwarder.start()
        self._cleanup = threading.Thread(target=self._cleanup_loop, name="imaging-cleanup", daemon=True)
        self._cleanup.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop.set()
        self.receiver.stop()
        self.forwarder.stop()
        self.store.log_event("info", "Imaging module stopped")

    def reconfigure(self, cfg: dict[str, Any]) -> None:
        """Apply new settings, restarting only what changed."""
        old_listen = {k: self.settings.get(k) for k in LISTEN_KEYS}
        old_plugins = self.settings.full_config().get("plugins")
        old_dests = self.settings.get("destinations")
        self.settings.replace_config(cfg)
        if not self.running:
            return
        if any(old_listen[k] != self.settings.get(k) for k in LISTEN_KEYS):
            self.receiver.start()
        if old_dests != self.settings.get("destinations") or old_plugins != cfg.get("plugins"):
            self.forwarder.reload()
            # New address or credentials: try paused destinations straight away
            for w in self.forwarder.workers.values():
                w.paused_until = 0
            self.forwarder.nudge()

    def set_remote_nodes(self, source: str, nodes: list[dict[str, Any]]) -> bool:
        """Imaging devices a plugin's platform says may send through this computer."""
        current = self.settings.get("remote_nodes") or {}
        if current.get(source) == nodes:
            return False
        current[source] = nodes
        self.settings.update(remote_nodes=current)
        name = getattr(plugins.get(source), "name", source)
        self.store.log_event("info", f"Allowed imaging devices updated from {name} ({len(nodes)})")
        return True

    # ------------------------------------------------------------------ housekeeping
    def _cleanup_loop(self) -> None:
        while not self._stop.wait(CLEANUP_SECONDS):
            try:
                self.cleanup_once()
            except Exception:
                log.exception("imaging clean-up failed")

    def cleanup_once(self) -> int:
        days = float(self.settings.get("retention_days") or 7)
        rows = self.store.deletable(time.time() - days * 86400)
        deleted = []
        for row in rows:
            try:
                os.remove(row["path"])
            except FileNotFoundError:
                pass
            except OSError:
                continue
            deleted.append(row["id"])
        self.store.mark_file_deleted(deleted)
        images = self.home / "images"
        if images.exists():
            for folder in sorted((p for p in images.rglob("*") if p.is_dir()), key=lambda p: len(p.parts),
                                 reverse=True):
                try:
                    folder.rmdir()
                except OSError:
                    pass
        return len(deleted)

    # ------------------------------------------------------------------ status
    def retry(self, study_instance_uid: str | None = None) -> int:
        n = self.store.retry(study_instance_uid=study_instance_uid)
        for w in self.forwarder.workers.values():
            w.paused_until = 0
        self.forwarder.nudge()
        return n

    def report(self) -> dict[str, Any]:
        counts = self.store.counts()
        return {
            "queued": counts["totals"]["pending"] + counts["totals"]["sending"],
            "held": counts["totals"]["held"],
            "failed": counts["totals"]["failed"],
            "received_24h": counts["received_24h"],
            "listening": bool(self.receiver.listening_on),
            "listener_error": self.receiver.error,
            "ae_title": self.settings.get("ae_title"),
            "port": self.settings.get("port"),
            "disk_free_mb": int(shutil.disk_usage(self.home).free / (1024 * 1024)),
            "destinations": [{"id": d["id"], "name": d["name"], "paused_for": d["paused_for"],
                              "error": d["last_error"]} for d in self.forwarder.status()],
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "listening_on": self.receiver.listening_on,
            "error": self.receiver.error,
            "last_refused": self.receiver.last_refused,
            "last_received_at": self.receiver.last_received_at,
            "counts": self.store.counts(),
            "destinations": self.forwarder.status(),
            "allowed_nodes": self.receiver.allowed_nodes(),
        }
