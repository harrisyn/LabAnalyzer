"""Imaging module and the Serenity link, end to end: real DICOM associations
(pynetdicom as the modality) and a fake Serenity device gateway."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import shutil
import socket
import subprocess
import time

import pydicom
import pytest
from pydicom.uid import generate_uid
from pynetdicom import AE, ALL_TRANSFER_SYNTAXES, AllStoragePresentationContexts, evt
from pynetdicom.sop_class import Verification

from dicom_helpers import KEY, FakeSerenity, free_port, make_dataset, send, split_multipart, wait_until
from labsync.config import ConfigManager, SecretStore, default_config, new_destination, new_device, validate
from labsync.engine import Engine
from labsync.imaging import forwarder
from labsync.imaging.destinations import MultipartStream
from labsync.imaging.service import ImagingService
from labsync.serenity import apply_setup_code, decode_setup_code
from labsync.storage.db import Database


@pytest.fixture
def serenity():
    fake = FakeSerenity()
    fake.start()
    yield fake
    try:
        fake.stop()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(forwarder, "RETRY_WAITS", [0.2])
    monkeypatch.setattr(forwarder, "HOLD_WAITS", [0.3])
    monkeypatch.setattr(forwarder, "PAUSE_WAITS", [0.3])


def imaging_config(serenity, **imaging):
    cfg = default_config()
    cfg["serenity"].update(url=serenity.url, device_key=KEY)
    cfg["imaging"].update(enabled=True, port=free_port(), min_free_disk_mb=1,
                          local_nodes=[{"name": "Test US", "ae_title": "US_ROOM1", "ip": ""}], **imaging)
    return cfg


def configure(svc: ImagingService, **imaging) -> None:
    cfg = copy.deepcopy(svc.settings._cfg)
    cfg["imaging"].update(imaging)
    svc.reconfigure(cfg)


@pytest.fixture
def svc(tmp_path, serenity):
    s = ImagingService(imaging_config(serenity), tmp_path / "imaging")
    s.start()
    yield s
    s.stop()


def port_of(svc: ImagingService) -> int:
    return int(svc.settings.get("port"))


def states(svc: ImagingService, dest: str = "serenity") -> dict[str, int]:
    with svc.store.connect() as db:
        rows = db.execute("SELECT state, COUNT(*) FROM deliveries WHERE destination = ? GROUP BY state",
                          (dest,)).fetchall()
    return {r[0]: r[1] for r in rows}


# --------------------------------------------------------------------------- imaging module


def test_receives_and_forwards_a_study(svc, serenity):
    study = generate_uid()
    datasets = [make_dataset(accession="OK1", study_uid=study) for _ in range(12)]
    assert send(port_of(svc), datasets) == [0] * 12
    assert wait_until(lambda: len(serenity.received) == 12)
    assert {r["sop"] for r in serenity.received} == {str(d.SOPInstanceUID) for d in datasets}
    assert serenity.requests <= 6  # batched
    assert wait_until(lambda: states(svc) == {"done": 12})
    files = list((svc.home / "images").rglob("*.dcm"))
    assert len(files) == 12
    assert pydicom.dcmread(str(files[0])).AccessionNumber == "OK1"


def test_unknown_device_and_wrong_called_ae_are_refused(svc):
    port = port_of(svc)
    assert send(port, [make_dataset()], calling="STRANGER") is None
    assert send(port, [make_dataset()], called="WRONG_AE") is None
    assert "STRANGER" in (svc.receiver.last_refused or "") or "WRONG_AE" in (svc.receiver.last_refused or "")
    configure(svc, local_nodes=[{"name": "CT", "ae_title": "CT1", "ip": "10.9.9.9"}])
    assert send(port, [make_dataset()], calling="CT1") is None
    configure(svc, local_nodes=[{"name": "CT", "ae_title": "CT1", "ip": "127.0.0.0/8"}])
    assert send(port, [make_dataset()], calling="CT1") == [0]


def test_keeps_images_while_serenity_is_offline_and_sends_when_back(svc, serenity):
    serenity.stop()
    datasets = [make_dataset(accession="OK2") for _ in range(5)]
    assert send(port_of(svc), datasets) == [0] * 5  # the modality still gets Success
    assert wait_until(lambda: svc.forwarder.workers["serenity"].last_error != "")
    time.sleep(0.5)
    assert states(svc).get("done", 0) == 0
    with svc.store.connect() as db:  # nothing counted against the images while unreachable
        assert db.execute("SELECT MAX(attempts) FROM deliveries").fetchone()[0] == 0
    serenity.restart()
    assert wait_until(lambda: states(svc) == {"done": 5}, timeout=15)
    assert len(serenity.received) == 5


def test_server_errors_pause_and_recover(svc, serenity):
    serenity.status_override = 503
    send(port_of(svc), [make_dataset(accession="OK3")])
    assert wait_until(lambda: "503" in svc.forwarder.workers["serenity"].last_error)
    serenity.status_override = None
    assert wait_until(lambda: states(svc) == {"done": 1}, timeout=10)


def test_transient_failure_is_retried(svc, serenity):
    send(port_of(svc), [make_dataset(accession="FLAKY1")])
    assert wait_until(lambda: states(svc) == {"done": 1}, timeout=10)
    assert len(serenity.received) == 1


def test_no_matching_order_is_held_then_delivered(svc, serenity):
    send(port_of(svc), [make_dataset(accession="HOLD1") for _ in range(2)])
    assert wait_until(lambda: states(svc) == {"held": 2})
    studies = svc.store.recent_studies(problems_only=True)
    assert studies and "No active order" in studies[0]["destinations"]["serenity"]["last_error"]
    serenity.hold_release.add("HOLD1")
    assert wait_until(lambda: states(svc) == {"done": 2}, timeout=10)


def test_held_too_long_becomes_failed_and_can_be_retried(svc, serenity):
    configure(svc, hold_retry_days=1)
    send(port_of(svc), [make_dataset(accession="HOLD2")])
    assert wait_until(lambda: states(svc) == {"held": 1})
    with svc.store.transaction() as db:
        db.execute("UPDATE deliveries SET first_held_at = ?, next_attempt_at = 0", (time.time() - 3 * 86400,))
    svc.forwarder.nudge()
    assert wait_until(lambda: states(svc) == {"failed": 1})
    serenity.hold_release.add("HOLD2")
    assert svc.retry() == 1
    assert wait_until(lambda: states(svc) == {"done": 1})


def test_rejected_file_is_failed_not_retried_forever(svc, serenity):
    send(port_of(svc), [make_dataset(accession="BAD1")])
    assert wait_until(lambda: states(svc) == {"failed": 1})
    time.sleep(0.6)
    assert serenity.requests == 1


def test_resend_after_fixing_accession_supersedes_the_held_copy(svc, serenity):
    sop = generate_uid()
    send(port_of(svc), [make_dataset(accession="HOLD3", sop_uid=sop)])
    assert wait_until(lambda: states(svc) == {"held": 1})
    send(port_of(svc), [make_dataset(accession="OK4", sop_uid=sop)])
    assert wait_until(lambda: len(serenity.received) == 1)
    assert serenity.received[0]["accession"] == "OK4"
    assert wait_until(lambda: states(svc).get("held", 0) == 0)
    assert len(list((svc.home / "images").rglob("*.dcm"))) == 1


def test_crash_recovery_requeues_files_left_on_disk(tmp_path, serenity):
    s = ImagingService(imaging_config(serenity), tmp_path / "h2")
    folder = s.home / "images" / "20260101" / "study"
    folder.mkdir(parents=True)
    make_dataset(accession="OK5").save_as(str(folder / "orphan.dcm"), write_like_original=False)
    (folder / ".partial.part").write_bytes(b"half")
    s.start()
    try:
        assert wait_until(lambda: len(serenity.received) == 1)
        assert not (folder / ".partial.part").exists()
    finally:
        s.stop()


def test_queue_survives_restart(tmp_path, serenity):
    serenity.stop()
    cfg = imaging_config(serenity)
    s = ImagingService(cfg, tmp_path / "h3")
    s.start()
    send(port_of(s), [make_dataset(accession="OK6") for _ in range(3)])
    s.stop()
    serenity.restart()
    s2 = ImagingService(cfg, tmp_path / "h3")
    s2.start()
    try:
        assert wait_until(lambda: len(serenity.received) == 3, timeout=15)
    finally:
        s2.stop()


def test_cleanup_deletes_only_delivered_images_past_retention(svc, serenity):
    send(port_of(svc), [make_dataset(accession="OK7"), make_dataset(accession="HOLD9")])
    assert wait_until(lambda: states(svc) == {"done": 1, "held": 1})
    with svc.store.transaction() as db:
        db.execute("UPDATE instances SET received_at = ?", (time.time() - 30 * 86400,))
    assert svc.cleanup_once() == 1
    remaining = list((svc.home / "images").rglob("*.dcm"))
    assert len(remaining) == 1 and pydicom.dcmread(str(remaining[0])).AccessionNumber == "HOLD9"


def test_low_disk_space_refuses_with_out_of_resources(svc):
    configure(svc, min_free_disk_mb=10**9)
    assert send(port_of(svc), [make_dataset()]) == [0xA700]


def test_copies_go_to_an_extra_dicom_node_too(svc, serenity):
    """E.g. the PostDICOM communicator, for devices that can only send to one place."""
    received = []

    def on_store(event):
        received.append(str(event.dataset.SOPInstanceUID))
        return 0

    other = AE(ae_title="POSTDICOM")
    for ctx in AllStoragePresentationContexts:
        other.add_supported_context(ctx.abstract_syntax, ALL_TRANSFER_SYNTAXES)
    other.add_supported_context(Verification)
    port = free_port()
    server = other.start_server(("127.0.0.1", port), block=False, evt_handlers=[(evt.EVT_C_STORE, on_store)])
    try:
        configure(svc, dicom_destinations=[{"id": "pd", "name": "PostDICOM", "ae_title": "POSTDICOM",
                                             "host": "127.0.0.1", "port": port, "enabled": True}])
        dest = [d for d in svc.destinations() if d.id == "dicom:pd"][0]
        assert dest.echo() is None
        send(port_of(svc), [make_dataset(accession="OK8") for _ in range(3)])
        assert wait_until(lambda: len(received) == 3 and len(serenity.received) == 3)
        assert wait_until(lambda: states(svc, "dicom:pd") == {"done": 3})
    finally:
        server.shutdown()


def test_changing_the_port_moves_the_listener(svc):
    new_port = free_port()
    configure(svc, port=new_port, ae_title="SITE_GW")
    assert wait_until(lambda: svc.receiver.listening_on and svc.receiver.listening_on[1] == new_port)
    assert send(new_port, [make_dataset(accession="OK10")], called="SITE_GW") == [0]


def test_port_in_use_is_reported_and_not_shared(tmp_path, serenity):
    taken = socket.socket()
    taken.bind(("0.0.0.0", 0))
    taken.listen(1)
    try:
        s = ImagingService(imaging_config(serenity), tmp_path / "h4")
        configure(s, port=taken.getsockname()[1])
        s.start()
        try:
            assert s.receiver.error and "Could not listen" in s.receiver.error
            assert not s.receiver.listening_on
        finally:
            s.stop()
    finally:
        taken.close()


def test_dcmtk_storescu_and_echoscu_interoperate(svc, serenity, tmp_path):
    if not shutil.which("storescu"):
        pytest.skip("dcmtk not installed")
    port = str(port_of(svc))
    echo = subprocess.run(["echoscu", "-aet", "US_ROOM1", "-aec", "SERENITY", "127.0.0.1", port],
                          capture_output=True, text=True, timeout=30)
    assert echo.returncode == 0, echo.stderr
    files = []
    for i in range(4):
        path = tmp_path / f"img{i}.dcm"
        make_dataset(accession="OK9").save_as(str(path), write_like_original=False)
        files.append(str(path))
    store = subprocess.run(["storescu", "-aet", "US_ROOM1", "-aec", "SERENITY", "127.0.0.1", port, *files],
                           capture_output=True, text=True, timeout=60)
    assert store.returncode == 0, store.stderr
    assert wait_until(lambda: len(serenity.received) == 4)


def test_multipart_stream_matches_what_serenity_parses(tmp_path):
    paths = []
    for i, content in enumerate([b"one", b"two\r\n--not-a-boundary", b""]):
        p = tmp_path / f"f{i}"
        p.write_bytes(content)
        paths.append(str(p))
    stream = MultipartStream(paths, "B0UND")
    body = b"".join(iter(lambda: stream.read(7), b""))
    assert len(body) == len(MultipartStream(paths, "B0UND"))
    assert split_multipart(body, "multipart/related; boundary=B0UND") == [b"one", b"two\r\n--not-a-boundary", b""]


# --------------------------------------------------------------------------- Serenity link and configuration


def _code(payload: dict) -> str:
    return "SRN1." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_setup_code_is_validated_and_key_kept_out_of_the_file(tmp_path):
    good = _code({"v": 1, "url": "https://api.example.org/v2", "key": "sdk_x", "device": "GW",
                  "organization": "Clinic", "device_id": "abc"})
    assert decode_setup_code(good)["key"] == "sdk_x"
    for bad in ("", "hello", "SRN1.!!!", "SRN1." + base64.urlsafe_b64encode(b'{"url":"x"}').decode()):
        with pytest.raises(ValueError):
            decode_setup_code(bad)
    cfg = apply_setup_code(default_config(), good)
    assert cfg["serenity"]["url"] == "https://api.example.org/v2" and cfg["serenity"]["organization"] == "Clinic"

    class MemoryKeyring(SecretStore):
        def __init__(self):
            self.values = {}

        @property
        def available(self):
            return True

        def get(self, key):
            return self.values.get(key, "")

        def set(self, key, value):
            self.values[key] = value
            return True

    mgr = ConfigManager(tmp_path / "config.json", MemoryKeyring())
    mgr.save(cfg)
    assert "sdk_x" not in (tmp_path / "config.json").read_text()
    assert ConfigManager(tmp_path / "config.json", mgr.secrets).load()["serenity"]["device_key"] == "sdk_x"


def test_old_config_files_gain_the_new_sections(tmp_path):
    path = tmp_path / "config.json"
    cfg = default_config()
    del cfg["imaging"]
    cfg["serenity"] = {"url": "https://x/v2"}
    path.write_text(json.dumps(cfg))
    loaded = ConfigManager(path, SecretStore(enabled=False)).load()
    assert loaded["imaging"]["port"] == 11113 and loaded["imaging"]["enabled"] is False
    assert loaded["serenity"]["url"] == "https://x/v2" and loaded["serenity"]["heartbeat_seconds"] == 60


def test_validation_catches_imaging_port_clashing_with_an_analyzer():
    cfg = default_config()
    cfg["devices"] = [new_device("sysmex_xn", port=11113)]
    cfg["imaging"]["enabled"] = True
    assert any("11113" in p and "imaging" in p for p in validate(cfg))
    cfg["imaging"]["ae_title"] = "X" * 17
    assert any("AE title" in p for p in validate(cfg))
    cfg["destinations"] = [new_destination("serenity")]
    assert any("connect to Serenity" in p for p in validate(cfg))


async def _engine(tmp_path, cfg):
    engine = Engine(cfg, Database(tmp_path / "labsync.db"))
    await engine.start()
    return engine


async def test_heartbeat_reports_both_modules_and_downloads_allowed_devices(tmp_path, serenity):
    cfg = imaging_config(serenity)
    cfg["serenity"]["heartbeat_seconds"] = 3600
    engine = await _engine(tmp_path, cfg)
    try:
        serenity.modalities = [{"name": "MRI", "ae_title": "mri_1", "allowed_ips": ["127.0.0.1"]}]
        await engine.heartbeat_once()
        assert engine.serenity.state["ok"] and engine.serenity.state["organization"] == "Test Clinic"
        report = serenity.heartbeats[-1]["report"]
        assert "lab" in report and report["imaging"]["listening"] and "queued" in report
        assert engine.imaging.settings.get("serenity_nodes")[0]["ae_title"] == "MRI_1"
        port = cfg["imaging"]["port"]
        assert await asyncio.to_thread(send, port, [make_dataset(accession="OK11")], "MRI_1") == [0]
        assert await asyncio.to_thread(wait_until, lambda: len(serenity.received) == 1)
    finally:
        await engine.stop()
    # The list survives a restart with no internet
    serenity.stop()
    engine = await _engine(tmp_path, cfg)
    try:
        assert engine.imaging.settings.get("serenity_nodes")[0]["ae_title"] == "MRI_1"
    finally:
        await engine.stop()


async def test_a_lab_change_keeps_the_dicom_listener_and_imaging_can_be_switched_off(tmp_path, serenity):
    cfg = imaging_config(serenity)
    engine = await _engine(tmp_path, cfg)
    try:
        server = engine.imaging.receiver._server
        cfg2 = copy.deepcopy(cfg)
        cfg2["devices"] = [new_device("sysmex_xn", port=free_port())]
        await engine.apply_config(cfg2)
        assert engine.imaging.receiver._server is server  # not restarted
        cfg3 = copy.deepcopy(cfg2)
        cfg3["imaging"]["enabled"] = False
        await engine.apply_config(cfg3)
        assert not engine.imaging_on
        assert await asyncio.to_thread(send, cfg["imaging"]["port"], [make_dataset()]) is None
    finally:
        await engine.stop()


async def test_lab_results_go_to_serenity_with_the_device_key(tmp_path, serenity):
    from test_pipeline import send_astm

    port = free_port()
    cfg = default_config()
    cfg["serenity"].update(url=serenity.url, device_key=KEY)
    dev = new_device("sysmex_xn", port=port)
    dev["transport"]["host"] = "127.0.0.1"
    dest = new_destination("serenity")
    cfg["devices"], cfg["destinations"] = [dev], [dest]
    assert not validate(cfg)
    engine = await _engine(tmp_path, cfg)
    try:
        assert "connected to Test Clinic" in await engine.test_destination(dest)
        await send_astm("127.0.0.1", port, 2, None)
        assert await asyncio.to_thread(wait_until, lambda: len(serenity.lab_results) == 2)
        body = serenity.lab_results[0]["body"]
        assert body["patient"]["sample_id"] and len(body["results"]) == 6  # the 1.x shape Serenity reads
        assert serenity.lab_results[0]["key"]  # Idempotency-Key
        # A revoked key keeps results queued rather than parking them
        await engine.apply_config({**cfg, "serenity": {**cfg["serenity"], "device_key": "sdk_revoked"}})
        await send_astm("127.0.0.1", port, 1, None)
        await asyncio.sleep(1.0)
        status = engine.destination_status()[dest["id"]]
        assert status["failed"] == 0 and status["pending"] == 1 and "device key" in status["last_error"]
    finally:
        await engine.stop()
