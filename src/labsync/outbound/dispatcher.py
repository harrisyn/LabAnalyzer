"""Outbox workers: one per destination, honouring realtime / interval / cron schedules with retry backoff."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from croniter import croniter

from ..storage.db import Database, report_from_json
from .senders import DeliveryError, Sender, make_sender

log = logging.getLogger("labsync.delivery")

BASE_DELAY = 10.0
MAX_DELAY = 3600.0


def backoff(attempts: int) -> float:
    delay = min(MAX_DELAY, BASE_DELAY * (2 ** max(0, attempts - 1)))
    return delay * random.uniform(0.85, 1.15)


class DestinationWorker:
    def __init__(self, dest: dict[str, Any], db: Database, context_for: Callable[[str], dict[str, Any]],
                 on_update: Callable[[str], None]):
        self.dest = dest
        self.id = dest["id"]
        self.name = dest.get("name") or self.id
        self.db = db
        self.context_for = context_for
        self.on_update = on_update
        self.sender: Sender = make_sender(dest)
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.last_error = ""
        self.last_success_at = ""
        sched = dest.get("schedule") or {}
        self.mode = sched.get("mode", "realtime")
        self.interval = float(sched.get("interval_minutes", 15)) * 60
        self.cron = sched.get("cron", "0 * * * *")
        self.max_attempts = int(dest.get("max_attempts", 0) or 0)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"dest-{self.id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self.sender.close()

    def wake(self) -> None:
        self._wake.set()

    async def _sleep_until_next_window(self) -> None:
        if self.mode == "interval":
            await self._wait(self.interval, wakeable=False)
        elif self.mode == "cron":
            now = datetime.now().astimezone()
            nxt = croniter(self.cron, now).get_next(datetime)
            await self._wait(max(1.0, (nxt - now).total_seconds()), wakeable=False)

    async def _wait(self, seconds: float, wakeable: bool = True) -> None:
        if not wakeable:
            await asyncio.sleep(seconds)
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        self._wake.clear()

    async def _run(self) -> None:
        log.info("delivery to %s started (%s)", self.name, self.mode)
        if self.mode != "realtime":
            await self._sleep_until_next_window()
        while True:
            try:
                await self.drain()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("delivery worker %s crashed; continuing", self.name)
            if self.mode == "realtime":
                nxt = self.db.next_due(self.id)
                if nxt is None:
                    await self._wait(300)
                else:
                    delay = (nxt - datetime.now(UTC)).total_seconds()
                    await self._wait(max(0.2, min(delay, 300)))
            else:
                await self._sleep_until_next_window()

    async def drain(self) -> int:
        """Send every item that is due now. Returns the number delivered."""
        delivered = 0
        while True:
            batch = self.db.due_outbox(self.id, limit=25)
            if not batch:
                return delivered
            for row in batch:
                ok = await self._deliver(row)
                delivered += int(ok)
                if not ok and self.last_error.startswith("connection error"):
                    # The endpoint is down: stop hammering it, retries are already scheduled.
                    return delivered

    async def _deliver(self, row) -> bool:
        report = report_from_json(json.loads(row["report_json"]))
        if self.dest.get("include_attachments"):
            full = self.db.load_report(row["report_db_id"], with_attachments=True)
            if full is not None:
                report.attachments = full.attachments
        ctx = {**self.context_for(row["device_id"]), "received_at": row["received_at"],
               "report_db_id": row["report_db_id"]}
        try:
            status, note = await self.sender.send(report, ctx)
        except DeliveryError as exc:
            self.last_error = str(exc)
            attempts = int(row["attempts"]) + 1
            if not exc.retryable or (self.max_attempts and attempts >= self.max_attempts):
                self.db.mark_failed(row["outbox_id"], str(exc), exc.status)
                log.error("delivery of %s to %s failed permanently: %s", report.specimen.id or report.id, self.name, exc)
            else:
                delay = backoff(attempts)
                self.db.mark_retry(row["outbox_id"], str(exc), delay, exc.status)
                log.warning("delivery of %s to %s failed (attempt %d), retrying in %.0fs: %s",
                            report.specimen.id or report.id, self.name, attempts, delay, exc)
            self.on_update(self.id)
            return False
        except Exception as exc:  # a bug in a formatter must not wedge the queue
            self.last_error = f"internal error: {exc}"
            log.exception("unexpected error delivering to %s", self.name)
            self.db.mark_retry(row["outbox_id"], self.last_error, backoff(int(row["attempts"]) + 1))
            self.on_update(self.id)
            return False
        self.db.mark_sent(row["outbox_id"], status, note)
        self.last_error = ""
        self.last_success_at = datetime.now(UTC).isoformat(timespec="seconds")
        log.info("delivered %s to %s", report.specimen.id or report.id, self.name)
        self.on_update(self.id)
        return True
