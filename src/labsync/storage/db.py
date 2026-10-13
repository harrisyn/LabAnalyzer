"""SQLite storage: raw message audit trail, normalised results and the delivery outbox.

Design notes
- Every inbound transmission is stored verbatim (``messages.raw``) before
  anything else happens, so nothing an instrument sends is ever lost, even if
  parsing or delivery fails. Messages can be re-parsed later.
- Results are written together with their outbox rows in one transaction
  (transactional outbox), so a crash can never leave a stored result that is
  silently never delivered.
- WAL journal mode lets the GUI read while the engine writes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..models import Attachment, LabMessage, Observation, Patient, PersonName, Report, Specimen

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'in',
    protocol TEXT NOT NULL,
    message_type TEXT NOT NULL,
    control_id TEXT,
    sender TEXT,
    peer TEXT,
    received_at TEXT NOT NULL,
    raw BLOB,
    report_count INTEGER NOT NULL DEFAULT 0,
    warnings TEXT,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS ix_messages_received ON messages(received_at);
CREATE INDEX IF NOT EXISTS ix_messages_device ON messages(device_id, received_at);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    device_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    specimen_id TEXT,
    patient_id TEXT,
    patient_name TEXT,
    is_qc INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 0,
    abnormal_count INTEGER NOT NULL DEFAULT 0,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reports_received ON reports(received_at);
CREATE INDEX IF NOT EXISTS ix_reports_specimen ON reports(specimen_id);
CREATE INDEX IF NOT EXISTS ix_reports_patient ON reports(patient_id);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    seq INTEGER,
    code TEXT,
    name TEXT,
    value TEXT,
    value_num REAL,
    units TEXT,
    reference_range TEXT,
    flags TEXT,
    status TEXT,
    observed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_obs_report ON observations(report_id);
CREATE INDEX IF NOT EXISTS ix_obs_code ON observations(code);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    name TEXT,
    mime TEXT,
    data BLOB
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    destination_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_attempt_at TEXT,
    last_error TEXT,
    response_code INTEGER,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(report_id, destination_id)
);
CREATE INDEX IF NOT EXISTS ix_outbox_due ON outbox(destination_id, status, next_attempt_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="milliseconds")


def report_from_json(data: dict[str, Any]) -> Report:
    p = data.get("patient") or {}
    s = data.get("specimen") or {}
    patient = Patient(**{**p, "name": PersonName(**(p.get("name") or {}))})
    return Report(
        id=data["id"],
        patient=patient,
        specimen=Specimen(**s),
        observations=[Observation(**o) for o in data.get("observations", [])],
        comments=list(data.get("comments", [])),
        is_qc=bool(data.get("is_qc")),
        qc_info=dict(data.get("qc_info") or {}),
    )


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _tx(self):
        db = self

        class _Tx:
            def __enter__(self_inner):
                db._lock.acquire()
                db._conn.execute("BEGIN IMMEDIATE")
                return db._conn

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    db._lock.release()
                return False

        return _Tx()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)))

    # ------------------------------------------------------------------ writes
    def store_message(
        self,
        msg: LabMessage,
        destinations_for: Callable[[Report], list[str]] | None = None,
        direction: str = "in",
    ) -> tuple[int, list[tuple[int, Report]]]:
        stored: list[tuple[int, Report]] = []
        received = _iso(msg.received_at)
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO messages (device_id, direction, protocol, message_type, control_id, sender, peer,"
                " received_at, raw, report_count, warnings, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (msg.device_id, direction, msg.protocol, msg.message_type, msg.control_id, msg.sender, msg.peer,
                 received, msg.raw, len(msg.reports), json.dumps(msg.warnings) if msg.warnings else None,
                 json.dumps(msg.meta, default=str) if msg.meta else None),
            )
            message_id = int(cur.lastrowid)
            for report in msg.reports:
                rdata = asdict(report)
                rdata.pop("attachments", None)
                cur = c.execute(
                    "INSERT INTO reports (uuid, message_id, device_id, received_at, specimen_id, patient_id,"
                    " patient_name, is_qc, observation_count, abnormal_count, report_json)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (report.id, message_id, msg.device_id, received, report.specimen.id, report.patient.id,
                     report.patient.name.full, int(report.is_qc), len(report.observations), report.abnormal_count,
                     json.dumps(rdata, default=str)),
                )
                rid = int(cur.lastrowid)
                c.executemany(
                    "INSERT INTO observations (report_id, seq, code, name, value, value_num, units,"
                    " reference_range, flags, status, observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(rid, o.sequence, o.code, o.name, o.value, o.numeric_value, o.units, o.reference_range,
                      ",".join(o.flags), o.status, o.observed_at) for o in report.observations],
                )
                if report.attachments:
                    c.executemany(
                        "INSERT INTO attachments (report_id, name, mime, data) VALUES (?,?,?,?)",
                        [(rid, a.name, a.mime, a.data) for a in report.attachments],
                    )
                if destinations_for is not None:
                    now = _now()
                    c.executemany(
                        "INSERT OR IGNORE INTO outbox (report_id, destination_id, status, next_attempt_at, created_at)"
                        " VALUES (?,?,'pending',?,?)",
                        [(rid, d, now, now) for d in destinations_for(report)],
                    )
                stored.append((rid, report))
        return message_id, stored

    def enqueue(self, report_ids: Iterable[int], destination_id: str) -> int:
        now = _now()
        with self._tx() as c:
            cur = c.executemany(
                "INSERT INTO outbox (report_id, destination_id, status, next_attempt_at, created_at)"
                " VALUES (?,?,'pending',?,?) ON CONFLICT(report_id, destination_id) DO UPDATE SET"
                " status='pending', next_attempt_at=excluded.next_attempt_at, last_error=NULL",
                [(rid, destination_id, now, now) for rid in report_ids],
            )
            return cur.rowcount

    def mark_sent(self, outbox_id: int, response_code: int | None = None, note: str | None = None) -> None:
        now = _now()
        with self._tx() as c:
            c.execute(
                "UPDATE outbox SET status='sent', attempts=attempts+1, last_attempt_at=?, sent_at=?,"
                " response_code=?, last_error=? WHERE id=?",
                (now, now, response_code, note, outbox_id),
            )

    def mark_retry(self, outbox_id: int, error: str, delay_seconds: float, response_code: int | None = None) -> None:
        now = datetime.now(UTC)
        with self._tx() as c:
            c.execute(
                "UPDATE outbox SET status='pending', attempts=attempts+1, last_attempt_at=?, last_error=?,"
                " response_code=?, next_attempt_at=? WHERE id=?",
                (_iso(now), error[:2000], response_code, _iso(now + timedelta(seconds=delay_seconds)), outbox_id),
            )

    def mark_failed(self, outbox_id: int, error: str, response_code: int | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE outbox SET status='failed', attempts=attempts+1, last_attempt_at=?, last_error=?,"
                " response_code=? WHERE id=?",
                (_now(), error[:2000], response_code, outbox_id),
            )

    def retry_failed(self, destination_id: str | None = None, outbox_ids: Iterable[int] | None = None) -> int:
        now = _now()
        sql = "UPDATE outbox SET status='pending', next_attempt_at=? WHERE status='failed'"
        params: list[Any] = [now]
        if destination_id:
            sql += " AND destination_id=?"
            params.append(destination_id)
        ids = list(outbox_ids or [])
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        with self._tx() as c:
            return c.execute(sql, params).rowcount

    def reset_inflight(self) -> None:
        """Called at start-up: anything left 'sending' by a crash goes back to pending."""
        with self._tx() as c:
            c.execute("UPDATE outbox SET status='pending' WHERE status='sending'")

    def purge(self, older_than_days: int) -> int:
        if older_than_days <= 0:
            return 0
        cutoff = _iso(datetime.now(UTC) - timedelta(days=older_than_days))
        with self._tx() as c:
            # Keep anything still waiting to be delivered.
            c.execute(
                "DELETE FROM reports WHERE received_at < ? AND id NOT IN"
                " (SELECT report_id FROM outbox WHERE status IN ('pending','sending','failed'))",
                (cutoff,),
            )
            cur = c.execute(
                "DELETE FROM messages WHERE received_at < ? AND id NOT IN (SELECT message_id FROM reports"
                " WHERE message_id IS NOT NULL)", (cutoff,))
            return cur.rowcount

    # ------------------------------------------------------------------ reads
    def due_outbox(self, destination_id: str, limit: int = 50) -> list[sqlite3.Row]:
        return self.query(
            "SELECT o.id AS outbox_id, o.attempts, r.id AS report_db_id, r.uuid, r.device_id, r.received_at,"
            " r.report_json FROM outbox o JOIN reports r ON r.id=o.report_id"
            " WHERE o.destination_id=? AND o.status='pending' AND o.next_attempt_at<=?"
            " ORDER BY o.next_attempt_at, o.id LIMIT ?",
            (destination_id, _now(), limit),
        )

    def next_due(self, destination_id: str) -> datetime | None:
        rows = self.query(
            "SELECT MIN(next_attempt_at) AS t FROM outbox WHERE destination_id=? AND status='pending'",
            (destination_id,),
        )
        t = rows[0]["t"] if rows else None
        return datetime.fromisoformat(t) if t else None

    def load_report(self, report_db_id: int, with_attachments: bool = False) -> Report | None:
        rows = self.query("SELECT report_json FROM reports WHERE id=?", (report_db_id,))
        if not rows:
            return None
        report = report_from_json(json.loads(rows[0]["report_json"]))
        if with_attachments:
            for a in self.query("SELECT name, mime, data FROM attachments WHERE report_id=?", (report_db_id,)):
                report.attachments.append(Attachment(name=a["name"], mime=a["mime"], data=a["data"]))
        return report

    def outbox_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for row in self.query("SELECT destination_id, status, COUNT(*) AS n FROM outbox GROUP BY destination_id, status"):
            stats.setdefault(row["destination_id"], {})[row["status"]] = row["n"]
        return stats

    def failed_items(self, destination_id: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
        sql = ("SELECT o.id, o.destination_id, o.attempts, o.last_error, o.last_attempt_at, o.response_code,"
               " r.specimen_id, r.patient_id, r.device_id, r.received_at FROM outbox o JOIN reports r ON r.id=o.report_id"
               " WHERE o.status='failed'")
        params: list[Any] = []
        if destination_id:
            sql += " AND o.destination_id=?"
            params.append(destination_id)
        sql += " ORDER BY o.last_attempt_at DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def recent_reports(self, limit: int = 500, search: str = "", device_id: str = "",
                       since: str | None = None, include_qc: bool = True) -> list[sqlite3.Row]:
        sql = ("SELECT r.id, r.uuid, r.device_id, r.received_at, r.specimen_id, r.patient_id, r.patient_name,"
               " r.is_qc, r.observation_count, r.abnormal_count,"
               " (SELECT GROUP_CONCAT(o.status) FROM outbox o WHERE o.report_id=r.id) AS delivery"
               " FROM reports r WHERE 1=1")
        params: list[Any] = []
        if search:
            sql += " AND (r.specimen_id LIKE ? OR r.patient_id LIKE ? OR r.patient_name LIKE ?)"
            like = f"%{search}%"
            params += [like, like, like]
        if device_id:
            sql += " AND r.device_id=?"
            params.append(device_id)
        if since:
            sql += " AND r.received_at>=?"
            params.append(since)
        if not include_qc:
            sql += " AND r.is_qc=0"
        sql += " ORDER BY r.received_at DESC, r.id DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def report_delivery(self, report_db_id: int) -> list[sqlite3.Row]:
        return self.query(
            "SELECT id, destination_id, status, attempts, last_error, sent_at, response_code FROM outbox"
            " WHERE report_id=?", (report_db_id,))

    def report_message_raw(self, report_db_id: int) -> tuple[bytes, str]:
        rows = self.query(
            "SELECT m.raw, m.protocol FROM reports r JOIN messages m ON m.id=r.message_id WHERE r.id=?",
            (report_db_id,))
        return (bytes(rows[0]["raw"] or b""), rows[0]["protocol"]) if rows else (b"", "")

    def recent_messages(self, limit: int = 500, device_id: str = "") -> list[sqlite3.Row]:
        sql = ("SELECT id, device_id, direction, protocol, message_type, control_id, sender, peer, received_at,"
               " LENGTH(raw) AS size, report_count, warnings FROM messages")
        params: list[Any] = []
        if device_id:
            sql += " WHERE device_id=?"
            params.append(device_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def message_raw(self, message_id: int) -> bytes:
        rows = self.query("SELECT raw FROM messages WHERE id=?", (message_id,))
        return bytes(rows[0]["raw"] or b"") if rows else b""

    def counts_today(self) -> dict[str, int]:
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.query(
            "SELECT COUNT(*) AS reports, COALESCE(SUM(observation_count),0) AS results FROM reports WHERE received_at>=?",
            (_iso(start),))
        return {"reports": rows[0]["reports"], "results": rows[0]["results"]}
