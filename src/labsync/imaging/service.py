"""Wires the imaging module together: settings view, receiver, forwarder and disk clean-up.

Settings come from two places:
- the ``imaging`` and ``serenity`` sections of LabSync's configuration (what
  people set in the app), and
- runtime state kept next to the queue (``state.json``): the imaging devices
  Serenity last said may send through this LabSync, so the list survives a
  restart without internet.
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

from ..config import default_imaging
from .destinations import SERENITY, DicomDestination, SerenityDestination
from .forwarder import Forwarder
from .receiver import Receiver
from .store import Store

log = logging.getLogger("labsync.imaging")

CLEANUP_SECONDS = 600
RUNTIME_KEYS = ("serenity_nodes",)
LISTEN_KEYS = ("enabled", "ae_title", "port", "bind_address")


class ImagingSettings:
    """The ``config.get(key)`` view the receiver, forwarder and destinations expect."""

    def __init__(self, cfg: dict[str, Any], state_path: Path):
        self._lock = threading.RLock()
        self._cfg = copy.deepcopy(cfg)
        self.state_path = Path(state_path)
        self._state: dict[str, Any] = {"serenity_nodes": []}
        if self.state_path.exists():
            try:
                stored = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state.update({k: v for k, v in stored.items() if k in RUNTIME_KEYS})
            except (OSError, ValueError):
                log.warning("imaging state file unreadable; starting with no Serenity devices")

    def replace_config(self, cfg: dict[str, Any]) -> None:
        with self._lock:
            self._cfg = copy.deepcopy(cfg)

    def get(self, key: str) -> Any:
        with self._lock:
            if key in RUNTIME_KEYS:
                return copy.deepcopy(self._state.get(key))
            serenity = self._cfg.get("serenity") or {}
            if key == "serenity_url":
                return serenity.get("url", "") if serenity.get("enabled", True) else ""
            if key in ("device_key", "ca_bundle"):
                return serenity.get(key, "")
            imaging = {**default_imaging(), **(self._cfg.get("imaging") or {})}
            return copy.deepcopy(imaging.get(key))

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
        self.serenity = SerenityDestination(self.settings)
        self.receiver = Receiver(self.settings, self.store, self.home / "images", self.destination_ids,
                                 on_received=self._on_received)
        self.forwarder = Forwarder(self.store, self.settings, self.destinations)
        self.running = False
        self._stop = threading.Event()
        self._cleanup: threading.Thread | None = None
        self.on_change = None  # set by the engine: called when something worth showing happened

    # ------------------------------------------------------------------ destinations
    def destinations(self) -> list:
        dests = []
        if self.settings.get("send_to_serenity"):
            dests.append(self.serenity)
        for spec in self.settings.get("dicom_destinations") or []:
            if spec.get("enabled", True) and spec.get("id"):
                dests.append(DicomDestination(self.settings, spec))
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
        old = {k: self.settings.get(k) for k in (*LISTEN_KEYS, "dicom_destinations", "send_to_serenity",
                                                  "serenity_url", "device_key")}
        self.settings.replace_config(cfg)
        new = {k: self.settings.get(k) for k in old}
        if not self.running:
            return
        if any(old[k] != new[k] for k in LISTEN_KEYS):
            self.receiver.start()
        if old["dicom_destinations"] != new["dicom_destinations"] or old["send_to_serenity"] != new["send_to_serenity"]:
            self.forwarder.reload()
        if old["serenity_url"] != new["serenity_url"] or old["device_key"] != new["device_key"]:
            for w in self.forwarder.workers.values():
                w.paused_until = 0
            self.forwarder.nudge()

    def set_serenity_nodes(self, nodes: list[dict[str, Any]]) -> bool:
        if nodes == self.settings.get("serenity_nodes"):
            return False
        self.settings.update(serenity_nodes=nodes)
        self.store.log_event("info", f"Allowed imaging devices updated from Serenity ({len(nodes)})")
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
            "destinations": [{"name": d["name"], "paused_for": d["paused_for"], "error": d["last_error"]}
                             for d in self.forwarder.status() if d["id"] != SERENITY],
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
