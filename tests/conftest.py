from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("LABSYNC_NO_KEYRING", "1")

from labsync.models import LabMessage  # noqa: E402
from labsync.protocols.base import SessionContext  # noqa: E402


class FakeLink:
    peer = "test"

    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        self.closed = True

    def take(self) -> bytes:
        out = bytes(self.written)
        self.written.clear()
        return out


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LABSYNC_HOME", str(tmp_path / "home"))
    yield


def make_ctx(options: dict | None = None, orders=None):
    messages: list[LabMessage] = []
    outbound: list[LabMessage] = []

    async def on_message(msg: LabMessage) -> None:
        messages.append(msg)

    async def on_out(msg: LabMessage) -> None:
        outbound.append(msg)

    ctx = SessionContext(device_id="dev1", device_name="test-device", profile_id="test", options=options or {},
                         on_message=on_message, on_outbound=on_out, orders=orders,
                         logger=logging.getLogger("labsync.test"))
    return ctx, messages, outbound


async def connect(handler_cls, options: dict | None = None, orders=None):
    ctx, messages, outbound = make_ctx(options, orders)
    handler = handler_cls(ctx)
    link = FakeLink()
    await handler.connection_made(link)
    return handler, link, messages, outbound
