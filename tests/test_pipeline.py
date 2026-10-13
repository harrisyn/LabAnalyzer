"""Storage, delivery, configuration and an end-to-end engine run (analyzer socket -> HTTP endpoint)."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
from aiohttp import web

from labsync.config import (
    ConfigManager,
    SecretStore,
    default_config,
    migrate_v1,
    new_destination,
    new_device,
    validate,
)
from labsync.engine import Engine
from labsync.models import LabMessage, Observation, Report
from labsync.outbound.dispatcher import DestinationWorker
from labsync.outbound.senders import DeliveryError, FileSender, HttpSender, MllpSender
from labsync.storage.db import Database
from labsync.tools.simulator import send_astm


def _report(specimen="S1", qc=False) -> Report:
    r = Report()
    r.specimen.id = specimen
    r.is_qc = qc
    r.patient.id = "P1"
    r.observations = [Observation(code="GLU", value="5.5", units="mmol/L", flags=["N"])]
    return r


def _msg(*reports) -> LabMessage:
    return LabMessage(device_id="dev1", protocol="astm", raw=b"raw", reports=list(reports))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- storage


def test_store_and_outbox_lifecycle(tmp_path):
    db = Database(tmp_path / "x.db")
    _, stored = db.store_message(_msg(_report("A"), _report("B")), lambda r: ["d1"])
    assert len(stored) == 2
    due = db.due_outbox("d1")
    assert [json.loads(r["report_json"])["specimen"]["id"] for r in due] == ["A", "B"]
    db.mark_sent(due[0]["outbox_id"], 200)
    db.mark_retry(due[1]["outbox_id"], "boom", 3600)
    assert db.due_outbox("d1") == []
    assert db.outbox_stats()["d1"] == {"sent": 1, "pending": 1}
    db.mark_failed(due[1]["outbox_id"], "dead")
    assert db.retry_failed("d1") == 1
    assert len(db.due_outbox("d1")) == 1
    assert db.enqueue([stored[0][0]], "d1") == 1  # re-send a delivered report
    assert db.outbox_stats()["d1"] == {"pending": 2}
    assert db.load_report(stored[0][0]).specimen.id == "A"


def test_purge_keeps_undelivered(tmp_path):
    db = Database(tmp_path / "x.db")
    db.store_message(_msg(_report("A")), lambda r: ["d1"])
    db.store_message(_msg(_report("B")), None)
    db.query("SELECT 1")
    with db._tx() as c:
        c.execute("UPDATE reports SET received_at='2000-01-01T00:00:00+00:00'")
        c.execute("UPDATE messages SET received_at='2000-01-01T00:00:00+00:00'")
    db.purge(30)
    left = [r["specimen_id"] for r in db.query("SELECT specimen_id FROM reports")]
    assert left == ["A"]


# --------------------------------------------------------------------------- senders


@pytest.fixture
async def http_server():
    calls: list[dict] = []
    state = {"status": 200, "token_calls": 0}

    async def results(request: web.Request):
        calls.append({"headers": dict(request.headers), "body": await request.json()})
        return web.json_response({"ok": True}, status=state["status"])

    async def token(request: web.Request):
        state["token_calls"] += 1
        return web.json_response({"access_token": f"tok{state['token_calls']}", "expires_in": 3600})

    app = web.Application()
    app.router.add_post("/results", results)
    app.router.add_post("/token", token)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    yield f"http://127.0.0.1:{port}", calls, state
    await runner.cleanup()


async def test_http_sender_formats_and_errors(http_server):
    base, calls, state = http_server
    dest = {**new_destination("http"), "url": base + "/results",
            "auth": {"method": "api_key", "header": "X-API-Key", "api_key": "k"}}
    s = HttpSender(dest)
    status, _ = await s.send(_report(), {"device_name": "XN"})
    assert status == 200
    assert calls[0]["headers"]["X-API-Key"] == "k"
    assert calls[0]["body"]["schema"] == "labsync.result.v1"
    assert calls[0]["headers"]["Idempotency-Key"]
    state["status"] = 503
    with pytest.raises(DeliveryError) as e:
        await s.send(_report(), {})
    assert e.value.retryable
    state["status"] = 400
    with pytest.raises(DeliveryError) as e:
        await s.send(_report(), {})
    assert not e.value.retryable and e.value.status == 400
    await s.close()

    state["status"] = 200
    legacy = HttpSender({**dest, "payload_format": "legacy"})
    await legacy.send(_report("LEG"), {"legacy_analyzer_type": "SYSMEX XN-L", "instance_id": "I1"})
    body = calls[-1]["body"]
    assert body["patient"]["sample_id"] == "LEG" and body["analyzer_type"] == "SYSMEX XN-L" and body["results"]
    await legacy.close()


async def test_http_oauth2(http_server):
    base, calls, state = http_server
    dest = {**new_destination("http"), "url": base + "/results",
            "auth": {"method": "oauth2", "token_url": base + "/token", "client_id": "c", "client_secret": "s"}}
    s = HttpSender(dest)
    await s.send(_report(), {})
    await s.send(_report(), {})
    assert state["token_calls"] == 1
    assert calls[-1]["headers"]["Authorization"] == "Bearer tok1"
    await s.close()


async def test_http_connection_refused_is_retryable():
    s = HttpSender({**new_destination("http"), "url": f"http://127.0.0.1:{_free_port()}/x", "timeout": 3})
    with pytest.raises(DeliveryError) as e:
        await s.send(_report(), {})
    assert e.value.retryable and str(e.value).startswith("connection error")
    await s.close()


async def test_mllp_sender():
    received: list[bytes] = []

    async def lis(reader, writer):
        data = await reader.readuntil(b"\x1c\r")
        received.append(data)
        ctrl = data.decode().split("\r")[0].split("|")[9]
        writer.write(f"\x0bMSH|^~\\&|LIS||||||ACK|1|P|2.5.1\rMSA|AA|{ctrl}\r\x1c\r".encode())
        await writer.drain()

    server = await asyncio.start_server(lis, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    s = MllpSender({**new_destination("hl7_mllp"), "host": "127.0.0.1", "port": port})
    _, note = await s.send(_report("M1"), {"device_name": "XN"})
    assert note == "ACK AA"
    assert b"ORU^R01" in received[0] and b"M1" in received[0]
    await s.close()
    server.close()


async def test_file_sender(tmp_path):
    s = FileSender({**new_destination("file"), "folder": str(tmp_path / "out"), "format": "csv"})
    _, path = await s.send(_report("F/1"), {"device_name": "XN 1"})
    assert path.endswith(".csv") and "F_1" in path
    with open(path, encoding="utf-8") as fh:
        assert "GLU" in fh.read()
    assert not [p for p in (tmp_path / "out").iterdir() if p.name.startswith(".tmp-")]


async def test_worker_retries_then_parks(tmp_path, http_server):
    base, calls, state = http_server
    db = Database(tmp_path / "x.db")
    db.store_message(_msg(_report()), lambda r: ["d1"])
    dest = {**new_destination("http"), "id": "d1", "url": base + "/results", "max_attempts": 2}
    w = DestinationWorker(dest, db, lambda d: {}, lambda d: None)
    state["status"] = 500
    assert await w.drain() == 0
    assert db.outbox_stats()["d1"] == {"pending": 1}
    with db._tx() as c:
        c.execute("UPDATE outbox SET next_attempt_at='2000-01-01T00:00:00+00:00'")
    await w.drain()
    assert db.outbox_stats()["d1"] == {"failed": 1}
    state["status"] = 200
    db.retry_failed("d1")
    assert await w.drain() == 1
    await w.sender.close()


# --------------------------------------------------------------------------- config


V1 = {
    "app_name": "LabSync", "port": 5000, "analyzer_type": "SYSMEX XN-L", "instance_id": "LAB-1", "auto_start": True,
    "external_server": {"enabled": True, "url": "https://api.example.org/v2", "endpoint_path": "/results",
                        "auth_method": "api_key", "api_key": "secret", "api_key_header": "X-API-Key",
                        "sync_frequency": "scheduled", "scheduled_hour": 23, "scheduled_minute": 30},
}


def test_migrate_v1():
    cfg = migrate_v1(V1)
    assert not validate(cfg)
    (dev,) = cfg["devices"]
    assert dev["profile"].startswith("sysmex") and dev["transport"]["port"] == 5000
    (dest,) = cfg["destinations"]
    assert dest["url"] == "https://api.example.org/v2/results"
    assert dest["payload_format"] == "legacy" and dest["auth"]["api_key"] == "secret"
    assert dest["schedule"] == {"mode": "cron", "cron": "30 23 * * *"}


def test_validate_catches_problems():
    cfg = default_config()
    a, b = new_device("generic_astm", port=6000), new_device("generic_astm", port=6000)
    d = new_destination("http")
    d["url"] = "ftp://x"
    d["schedule"] = {"mode": "cron", "cron": "not cron"}
    cfg["devices"] = [a, b]
    cfg["destinations"] = [d]
    problems = " ".join(validate(cfg))
    assert "both listen on port 6000" in problems and "URL must start" in problems and "invalid cron" in problems


class MemoryKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, svc, key):
        return self.store.get((svc, key))

    def set_password(self, svc, key, value):
        self.store[(svc, key)] = value

    def delete_password(self, svc, key):
        self.store.pop((svc, key), None)


def test_config_manager_migrates_and_keeps_secrets_out_of_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(V1))
    secrets = SecretStore(enabled=False)
    secrets._kr = MemoryKeyring()
    mgr = ConfigManager(path, secrets)
    cfg = mgr.load()
    assert mgr.migrated_from == 1 and (tmp_path / "config.v1.backup.json").exists()
    assert cfg["destinations"][0]["auth"]["api_key"] == "secret"
    on_disk = path.read_text()
    assert "secret" not in on_disk and "__keyring__" in on_disk
    again = ConfigManager(path, secrets).load()
    assert again["destinations"][0]["auth"]["api_key"] == "secret"


def test_corrupt_config_is_backed_up(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{nope")
    cfg = ConfigManager(path, SecretStore(enabled=False)).load()
    assert cfg["devices"] == [] and (tmp_path / "config.corrupt.json").exists()


# --------------------------------------------------------------------------- end to end


async def test_engine_end_to_end_astm_to_http(tmp_path, http_server):
    base, calls, state = http_server
    port = _free_port()
    cfg = default_config()
    dev = new_device("sysmex_xn", port=port)
    dev["transport"]["host"] = "127.0.0.1"
    dest = {**new_destination("http"), "url": base + "/results", "payload_format": "labsync"}
    cfg["devices"], cfg["destinations"] = [dev], [dest]
    assert not validate(cfg)
    db = Database(tmp_path / "e.db")
    engine = Engine(cfg, db)
    await engine.start()
    try:
        await send_astm("127.0.0.1", port, 2, None)
        for _ in range(100):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.05)
        assert len(calls) == 2
        body = calls[0]["body"]
        assert body["device"]["name"] == dev["name"]
        assert len(body["results"]) == 6
        assert engine.destination_status()[dest["id"]]["sent"] == 2
    finally:
        await engine.stop()


# --------------------------------------------------------------------------- CLI


def test_cli_parse_and_profiles(tmp_path, capsys):
    from labsync.app import main
    from labsync.protocols.astm.framing import ENQ, EOT, build_frames
    from labsync.tools.simulator import astm_records

    capture = tmp_path / "cap.bin"
    capture.write_bytes(bytes([ENQ]) + b"".join(build_frames(astm_records("123456", "P1"))) + bytes([EOT]))
    assert main(["--home", str(tmp_path / "h"), "parse", str(capture), "--profile", "sysmex_xn_l"]) == 0
    out = json.loads(capsys.readouterr().out)
    (msg,) = out["messages"]
    assert msg["reports"][0]["specimen"]["id"] == "123456"
    assert main(["--home", str(tmp_path / "h"), "profiles"]) == 0
    assert "sysmex_xn_l" in capsys.readouterr().out
    assert main(["--home", str(tmp_path / "h"), "check-config"]) == 0
