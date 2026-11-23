"""The integration engine: devices in, storage, destinations out.

Two modules share it: the analyzer engine (devices, outbox, destinations, all
on this asyncio loop) and the imaging module (a DICOM node with its own
threads, queue and folder, see ``labsync.imaging``). Integration plugins
(``labsync.plugins``) add destination types and, optionally, a link to their
platform that the engine checks in with on a timer.

The engine runs on its own asyncio event loop. The desktop GUI starts it in a
background thread and talks to it through ``call`` (thread-safe coroutine
submission) and the ``events`` queue; headless mode runs it in the main
thread. Nothing in here imports tkinter.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import copy
import logging
import queue
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from . import __version__, plugins
from .devices.catalog import find_profile, merged_options
from .models import LabMessage, Report
from .outbound.dispatcher import DestinationWorker
from .outbound.orders import make_order_source
from .outbound.senders import make_sender
from .protocols import handler_for
from .protocols.base import SessionContext
from .storage.db import Database
from .transport.runner import DeviceRunner, DeviceStatus

log = logging.getLogger("labsync.engine")


class Engine:
    def __init__(self, config: dict[str, Any], db: Database, imaging_home: Path | None = None):
        self.config = copy.deepcopy(config)
        self.db = db
        if imaging_home is None and db.path != ":memory:":
            imaging_home = Path(db.path).parent / "imaging"
        self.imaging_home = imaging_home
        self.imaging = None  # ImagingService, created when the imaging module is first switched on
        self.links: dict[str, plugins.Link] = {}
        self._link_keys: dict[str, str] = {}
        self._link_tasks: dict[str, asyncio.Task] = {}
        self._sync_links()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=10000)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.runners: dict[str, DeviceRunner] = {}
        self.workers: dict[str, DestinationWorker] = {}
        self.running = False
        self._housekeeping: asyncio.Task | None = None
        self._orders = None

    # ------------------------------------------------------------------ threading helpers
    def start_in_thread(self) -> None:
        ready = threading.Event()

        def run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            ready.set()
            self.loop.run_forever()
            # Drain anything still scheduled, then close.
            pending = asyncio.all_tasks(self.loop)
            for t in pending:
                t.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

        self._thread = threading.Thread(target=run, name="labsync-engine", daemon=True)
        self._thread.start()
        ready.wait(5)

    def call(self, coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
        if self.loop is None:
            raise RuntimeError("engine loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown_thread(self, timeout: float = 10.0) -> None:
        if self.loop is None:
            return
        with contextlib.suppress(Exception):
            self.call(self.stop()).result(timeout)
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------------ events
    def _publish(self, kind: str, data: Any = None) -> None:
        try:
            self.events.put_nowait((kind, data))
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self.events.get_nowait()
            with contextlib.suppress(queue.Full):
                self.events.put_nowait((kind, data))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        await self._start_lab()
        await self._sync_imaging()
        self._start_link_tasks()
        self._housekeeping = asyncio.create_task(self._housekeeping_loop())
        log.info("engine started: %d device(s), %d destination(s), imaging %s", len(self.runners),
                 len(self.workers), "on" if self.imaging_on else "off")
        self._publish("engine", "started")

    async def _start_lab(self) -> None:
        self.db.reset_inflight()
        self._orders = make_order_source(self.config.get("orders"))
        for dest in self.config.get("destinations", []):
            if dest.get("enabled", True):
                worker = DestinationWorker(self._sender_config(dest), self.db, self._device_context,
                                           self._delivery_updated)
                self.workers[dest["id"]] = worker
                worker.start()
        for dev in self.config.get("devices", []):
            if dev.get("enabled", True):
                await self._start_device(dev)

    async def _stop_lab(self) -> None:
        for runner in list(self.runners.values()):
            with contextlib.suppress(Exception):
                await runner.stop()
        for worker in list(self.workers.values()):
            with contextlib.suppress(Exception):
                await worker.stop()
        self.runners.clear()
        self.workers.clear()

    def _sender_config(self, dest: dict[str, Any]) -> dict[str, Any]:
        """A destination type added by a plugin gets that plugin's settings (address, key...)."""
        owner = plugins.lab_destination_owner(self.config, dest.get("type", ""), only_enabled=False)
        if owner is not None:
            return {**dest, "_plugin_settings": copy.deepcopy(owner[1])}
        return dest

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        for task in (self._housekeeping, *self._link_tasks.values()):
            if task is not None:
                task.cancel()
        self._link_tasks.clear()
        await self._stop_lab()
        if self.imaging is not None and self.imaging.running:
            await asyncio.get_running_loop().run_in_executor(None, self.imaging.stop)
        log.info("engine stopped")
        self._publish("engine", "stopped")

    async def apply_config(self, config: dict[str, Any]) -> None:
        """Apply a new configuration. The analyzer side restarts; the imaging module only
        restarts the parts whose settings changed, so a lab change never drops a DICOM transfer."""
        if not self.running:
            self.config = copy.deepcopy(config)
            self._sync_links()
            return
        await self._stop_lab()
        self.config = copy.deepcopy(config)
        changed = self._sync_links()
        await self._start_lab()
        await self._sync_imaging()
        for pid in changed:
            task = self._link_tasks.pop(pid, None)
            if task is not None:
                task.cancel()
        self._start_link_tasks()
        self._publish("engine", "started")

    # ------------------------------------------------------------------ imaging
    @property
    def imaging_on(self) -> bool:
        return bool(self.imaging is not None and self.imaging.running)

    async def _sync_imaging(self) -> None:
        """Start, stop or reconfigure the imaging module to match the configuration."""
        wanted = bool((self.config.get("imaging") or {}).get("enabled")) and self.imaging_home is not None
        loop = asyncio.get_running_loop()
        if wanted and self.imaging is None:
            from .imaging.service import ImagingService  # pynetdicom is only loaded when imaging is used

            self.imaging = await loop.run_in_executor(None, ImagingService, self.config, self.imaging_home)
            self.imaging.on_change = lambda: self._publish_threadsafe("imaging", None)
        if self.imaging is None:
            return
        await loop.run_in_executor(None, self.imaging.reconfigure, self.config)
        if wanted and not self.imaging.running:
            await loop.run_in_executor(None, self.imaging.start)
        elif not wanted and self.imaging.running:
            await loop.run_in_executor(None, self.imaging.stop)
        self._publish("imaging", None)

    def _publish_threadsafe(self, kind: str, data: Any = None) -> None:
        # queue.Queue is thread-safe; _publish only touches it
        self._publish(kind, data)

    async def retry_imaging(self, study_instance_uid: str | None = None) -> int:
        if self.imaging is None:
            return 0
        return await asyncio.get_running_loop().run_in_executor(None, self.imaging.retry, study_instance_uid)

    def imaging_status(self) -> dict[str, Any] | None:
        return self.imaging.status() if self.imaging is not None else None

    # ------------------------------------------------------------------ plugin links
    def _sync_links(self) -> set[str]:
        """Create, replace or drop plugin links to match the configuration; return the ids that changed."""
        import json

        changed: set[str] = set()
        wanted = {p.id: (p, s) for p, s in plugins.enabled(self.config)}
        for pid in list(self.links):
            if pid not in wanted:
                self.links.pop(pid).close()
                self._link_keys.pop(pid, None)
                changed.add(pid)
                self._publish("plugin", pid)
        for pid, (plugin, settings) in wanted.items():
            key = json.dumps(settings, sort_keys=True, default=str)
            if self._link_keys.get(pid) == key:
                continue
            old = self.links.pop(pid, None)
            if old is not None:
                old.close()
            link = plugin.make_link(settings)
            self._link_keys[pid] = key
            changed.add(pid)
            if link is not None:
                self.links[pid] = link
        return changed

    def _start_link_tasks(self) -> None:
        for pid in self.links:
            task = self._link_tasks.get(pid)
            if task is None or task.done():
                self._link_tasks[pid] = asyncio.create_task(self._link_loop(pid), name=f"plugin-{pid}")

    def link_states(self) -> dict[str, tuple[str, plugins.LinkState]]:
        """{plugin id: (plugin name, state)} for every enabled plugin with a link."""
        out = {}
        for pid, link in self.links.items():
            plugin = plugins.get(pid)
            out[pid] = (plugin.name if plugin else pid, copy.copy(link.state))
        return out

    def status_report(self) -> dict[str, Any]:
        lab = {
            "devices": [
                {"id": k, "name": r.name, "state": r.status.state, "detail": r.status.detail,
                 "messages": r.status.messages, "last_message_at": r.status.last_message_at}
                for k, r in self.runners.items()
            ],
            "outbox": self.db.outbox_stats(),
        }
        report: dict[str, Any] = {"lab": lab}
        if self.imaging_on:
            report["imaging"] = self.imaging.report()
            # Kept at the top level too for platforms that read the imaging queue size from here
            report.update({k: report["imaging"][k] for k in ("queued", "held", "failed", "received_24h",
                                                              "listening", "listener_error")})
        return report

    async def check_link(self, plugin_id: str) -> None:
        """Check in with one plugin's platform now (status out, allowed imaging devices back)."""
        link = self.links.get(plugin_id)
        if link is None:
            return
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(None, link.check, self.status_report())
        if answer is not None and self.imaging is not None:
            nodes = link.remote_nodes(answer)
            if nodes is not None:
                await loop.run_in_executor(None, self.imaging.set_remote_nodes, plugin_id, nodes)
        self._publish("plugin", plugin_id)

    async def check_links(self) -> None:
        for pid in list(self.links):
            await self.check_link(pid)

    async def _link_loop(self, plugin_id: str) -> None:
        while plugin_id in self.links:
            try:
                await self.check_link(plugin_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("check-in with plugin %s failed", plugin_id)
            link = self.links.get(plugin_id)
            await asyncio.sleep(max(10, int(getattr(link, "interval_seconds", 60) or 60)))

    async def restart_device(self, device_id: str) -> None:
        runner = self.runners.pop(device_id, None)
        if runner is not None:
            await runner.stop()
        dev = self._device(device_id)
        if dev is not None and dev.get("enabled", True) and self.running:
            await self._start_device(dev)

    async def _start_device(self, dev: dict[str, Any]) -> None:
        profile = find_profile(dev.get("profile", ""))
        if profile is None:
            log.error("device %s: unknown profile %s", dev.get("name"), dev.get("profile"))
            return
        options = merged_options(profile, dev.get("options"))
        protocol = options.pop("protocol", None) or profile.protocol
        handler_cls = handler_for(protocol)
        name = dev.get("name") or dev["id"]
        dev_log = logging.getLogger(f"labsync.device.{dev['id']}")

        def factory() -> Any:
            ctx = SessionContext(
                device_id=dev["id"], device_name=name, profile_id=profile.id, options=copy.deepcopy(options),
                on_message=self._on_message, on_outbound=self._on_outbound, orders=self._orders, logger=dev_log)
            return handler_cls(ctx)

        runner = DeviceRunner(dev, factory, self._status_changed)
        self.runners[dev["id"]] = runner
        await runner.start()

    async def _housekeeping_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            days = int(self.config.get("retention_days", 0) or 0)
            if days > 0:
                try:
                    n = self.db.purge(days)
                    if n:
                        log.info("retention: removed %d message(s) older than %d days", n, days)
                except Exception:
                    log.exception("retention purge failed")

    # ------------------------------------------------------------------ callbacks
    def _device(self, device_id: str) -> dict[str, Any] | None:
        return next((d for d in self.config.get("devices", []) if d.get("id") == device_id), None)

    def _device_context(self, device_id: str) -> dict[str, Any]:
        dev = self._device(device_id) or {"id": device_id, "name": device_id}
        profile = find_profile(dev.get("profile", ""))
        return {
            "instance_id": self.config.get("instance_id", ""),
            "device_id": device_id,
            "device_name": dev.get("name", device_id),
            "profile": dev.get("profile", ""),
            "vendor": profile.vendor if profile else "",
            "model": profile.model if profile else "",
            "protocol": profile.protocol if profile else "",
            "legacy_analyzer_type": (dev.get("options") or {}).get("legacy_analyzer_type", ""),
            "app_version": __version__,
        }

    def _destinations_for(self, device_id: str):
        def pick(report: Report) -> list[str]:
            out = []
            for dest in self.config.get("destinations", []):
                if not dest.get("enabled", True):
                    continue
                devices = dest.get("devices") or []
                if devices and device_id not in devices:
                    continue
                if report.is_qc and not dest.get("include_qc", False):
                    continue
                if not report.observations and not dest.get("include_empty", False):
                    continue
                out.append(dest["id"])
            return out

        return pick

    async def _on_message(self, msg: LabMessage) -> None:
        try:
            message_id, stored = self.db.store_message(msg, self._destinations_for(msg.device_id))
        except Exception:
            log.exception("failed to store message from %s", msg.device_id)
            self._publish("error", f"storage failure for {msg.device_id}")
            return
        runner = self.runners.get(msg.device_id)
        if runner is not None:
            runner.note_message()
        n_obs = sum(len(r.observations) for _, r in stored)
        if stored:
            log.info("[%s] stored %d report(s), %d result(s) (%s)", runner.name if runner else msg.device_id,
                     len(stored), n_obs, ", ".join(r.specimen.id or "?" for _, r in stored))
        elif msg.message_type not in ("status", "event"):
            log.info("[%s] stored %s message with no results", runner.name if runner else msg.device_id,
                     msg.message_type)
        for w in msg.warnings:
            log.warning("[%s] %s", msg.device_id, w)
        for worker in self.workers.values():
            worker.wake()
        self._publish("message", {"message_id": message_id, "device_id": msg.device_id,
                                  "reports": [rid for rid, _ in stored], "results": n_obs})

    async def _on_outbound(self, msg: LabMessage) -> None:
        with contextlib.suppress(Exception):
            self.db.store_message(msg, None, direction="out")
        self._publish("message", {"device_id": msg.device_id, "direction": "out"})

    def _status_changed(self, status: DeviceStatus) -> None:
        self._publish("device", copy.copy(status))

    def _delivery_updated(self, dest_id: str) -> None:
        self._publish("delivery", dest_id)

    # ------------------------------------------------------------------ API for the GUI / CLI
    def device_statuses(self) -> dict[str, DeviceStatus]:
        return {k: copy.copy(r.status) for k, r in self.runners.items()}

    def destination_status(self) -> dict[str, dict[str, Any]]:
        stats = self.db.outbox_stats()
        out = {}
        for dest in self.config.get("destinations", []):
            w = self.workers.get(dest["id"])
            out[dest["id"]] = {
                **{k: 0 for k in ("pending", "sent", "failed")},
                **stats.get(dest["id"], {}),
                "running": w is not None,
                "last_error": w.last_error if w else "",
                "last_success_at": w.last_success_at if w else "",
            }
        return out

    async def retry_failed(self, destination_id: str | None = None, ids: list[int] | None = None) -> int:
        n = self.db.retry_failed(destination_id, ids)
        for w in self.workers.values():
            w.wake()
        return n

    async def resend_reports(self, report_ids: list[int], destination_id: str) -> int:
        n = self.db.enqueue(report_ids, destination_id)
        w = self.workers.get(destination_id)
        if w:
            w.wake()
        return n

    async def flush_now(self, destination_id: str) -> int:
        w = self.workers.get(destination_id)
        return await w.drain() if w else 0

    async def test_destination(self, dest: dict[str, Any]) -> str:
        sender = make_sender(self._sender_config(dest))
        try:
            return await sender.test()
        finally:
            await sender.close()
