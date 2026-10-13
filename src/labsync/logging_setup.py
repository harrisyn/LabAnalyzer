"""Logging configuration: rotating file log, console, and an in-memory feed for the GUI."""

from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class QueueFeedHandler(logging.Handler):
    """Pushes formatted records into a bounded queue that the GUI drains."""

    def __init__(self, maxsize: int = 5000):
        super().__init__()
        self.queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=maxsize)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(record)
            except (queue.Empty, queue.Full):
                pass


_feed: QueueFeedHandler | None = None


def configure_logging(log_dir: Path, level: str = "INFO", console: bool = True) -> QueueFeedHandler:
    """Configure the root ``labsync`` logger. Safe to call more than once."""
    global _feed
    logger = logging.getLogger("labsync")
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "labsync.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # A windowed (frozen) build has no usable stdout on Windows.
    if console and sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    _feed = QueueFeedHandler()
    _feed.setFormatter(formatter)
    logger.addHandler(_feed)
    return _feed


def log_feed() -> QueueFeedHandler | None:
    return _feed
