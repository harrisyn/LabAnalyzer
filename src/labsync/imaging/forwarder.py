"""Sends queued images to each destination until they arrive.

One worker thread per destination. Each round it takes a batch of due images
(same study, up to N files / M bytes) and sends them.

- stored  -> done
- retry   -> try again with growing waits: 30 s, 1, 2, 5, 10, then every 15 min, forever
- hold    -> Serenity has no matching order yet. Try again at 5, 15, 30 min, then
             hourly for hold_retry_days (default 7), then mark failed (still
             retryable from the page).
- reject  -> failed; never sent again unless retried by hand
- destination unreachable (offline, Serenity down, bad key) -> nothing is counted
  against the images; the whole destination pauses 15 s, 30 s, 1, 2, 5 min...
"""

import logging
import threading
import time
from collections.abc import Callable

from .destinations import HOLD, REJECT, RETRY, STORED, Unreachable
from .store import Store

logger = logging.getLogger(__name__)

RETRY_WAITS = [30, 60, 120, 300, 600, 900]
HOLD_WAITS = [300, 900, 1800, 3600]
PAUSE_WAITS = [15, 30, 60, 120, 300]
BATCH_SETTLE_SECONDS = 1.0


def wait_for(waits: list[int], attempt: int) -> int:
    return waits[min(attempt, len(waits) - 1)]


class DestinationWorker:
    def __init__(self, destination, store: Store, config, wake: threading.Event):
        self.destination = destination
        self.store = store
        self.config = config
        self.wake = wake
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"send-{destination.id}", daemon=True)
        self.paused_until = 0.0
        self.pause_count = 0
        self.last_error = ""
        self.last_success_at = None
        self.sent_total = 0

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def status(self) -> dict:
        now = time.time()
        return {
            "id": self.destination.id,
            "name": self.destination.name,
            "configured": self.destination.configured,
            "paused_for": max(0, int(self.paused_until - now)),
            "last_error": self.last_error,
            "last_success_at": self.last_success_at,
            "sent_since_start": self.sent_total,
        }

    def _run(self):
        while not self.stop_event.is_set():
            try:
                did_work = self.run_once()
            except Exception:
                logger.exception("sending to %s crashed; continuing", self.destination.id)
                did_work = False
            if not did_work and self.wake.wait(timeout=5):
                self.wake.clear()
                # Images of a study arrive a few per second: wait a
                # moment so they go together in one request.
                self.stop_event.wait(BATCH_SETTLE_SECONDS)

    def run_once(self) -> bool:
        now = time.time()
        if now < self.paused_until or not self.destination.configured:
            return False
        rows = self.store.claim_due(
            self.destination.id,
            int(self.config.get("batch_max_instances") or 10),
            int(self.config.get("batch_max_bytes") or 40 * 1024 * 1024),
        )
        if not rows:
            return False
        # Files deleted by hand can never be sent
        import os

        present = [r for r in rows if os.path.exists(r["path"])]
        present_ids = {r["instance_id"] for r in present}
        for r in rows:
            if r["instance_id"] not in present_ids:
                self.store.mark(r["instance_id"], self.destination.id, "failed", error="File is missing from disk",
                                outcome=REJECT)
        if not present:
            return True
        try:
            outcomes = self.destination.send(present)
        except Unreachable as exc:
            wait = wait_for(PAUSE_WAITS, self.pause_count)
            self.pause_count += 1
            self.paused_until = time.time() + wait
            message = str(exc)
            if message != self.last_error:
                self.store.log_event("warning", f"{self.destination.name}: {message}. Images are kept and will be sent when it's back.")
            self.last_error = message
            self.store.release_sending(self.destination.id, self.paused_until, message)
            logger.warning("%s unreachable (%s); pausing %ss", self.destination.id, message, wait)
            return False
        except Exception as exc:
            logger.exception("sending to %s failed", self.destination.id)
            self.store.release_sending(self.destination.id, time.time() + 60, f"{exc.__class__.__name__}: {exc}")
            self.last_error = str(exc)
            return False

        if self.pause_count:
            self.store.log_event("info", f"{self.destination.name}: connection is back")
        self.pause_count = 0
        self.last_error = ""
        self._apply(present, outcomes)
        return True

    def _apply(self, rows, outcomes):
        now = time.time()
        hold_days = float(self.config.get("hold_retry_days") or 7)
        for row, result in zip(rows, outcomes, strict=False):
            dest = self.destination.id
            if result.outcome == STORED:
                self.store.mark(row["instance_id"], dest, "done", outcome=STORED)
                self.sent_total += 1
                self.last_success_at = now
            elif result.outcome == HOLD:
                first = row["first_held_at"] or now
                if now - first > hold_days * 86400:
                    self.store.mark(row["instance_id"], dest, "failed", error=result.detail, outcome=HOLD)
                    self.store.log_event("error", f"{self.destination.name}: gave up after {hold_days:g} days on "
                                                  f"accession {row['accession_number'] or '(none)'}: {result.detail}")
                else:
                    held_count = row["attempts"] if row["state"] == "held" else 0
                    self.store.mark(row["instance_id"], dest, "held", outcome=HOLD, error=result.detail,
                                    next_attempt_at=now + wait_for(HOLD_WAITS, held_count), held_since=first)
            elif result.outcome == REJECT:
                self.store.mark(row["instance_id"], dest, "failed", error=result.detail, outcome=REJECT)
                self.store.log_event("error", f"{self.destination.name} refused {row['sop_instance_uid']}: {result.detail}")
            else:  # retry
                self.store.mark(row["instance_id"], dest, "pending", outcome=RETRY, error=result.detail,
                                next_attempt_at=now + wait_for(RETRY_WAITS, row["attempts"]))


class Forwarder:
    def __init__(self, store: Store, config, destinations_factory: Callable[[], list]):
        self.store = store
        self.config = config
        self.factory = destinations_factory
        self.wake = threading.Event()
        self.workers: dict[str, DestinationWorker] = {}

    def start(self):
        self.reload()

    def reload(self):
        """(Re)create workers to match the configured destinations."""
        wanted = {d.id: d for d in self.factory()}
        for dest_id in list(self.workers):
            if dest_id not in wanted:
                self.workers.pop(dest_id).stop()
        for dest_id, dest in wanted.items():
            worker = self.workers.get(dest_id)
            if worker is not None:
                worker.destination = dest
                continue
            worker = DestinationWorker(dest, self.store, self.config, self.wake)
            self.workers[dest_id] = worker
            worker.start()
        self.nudge()

    def nudge(self):
        self.wake.set()

    def stop(self):
        for worker in self.workers.values():
            worker.stop()

    def status(self) -> list[dict]:
        return [w.status() for w in self.workers.values()]
