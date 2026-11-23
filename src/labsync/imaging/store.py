"""The on-disk queue: every received instance and its delivery to each
destination. SQLite in WAL mode; each thread gets its own connection.

instances    one row per received SOP instance (the file is in images/)
deliveries   one row per (instance, destination): pending / sending / done /
             held / failed, with attempts, next attempt and the last error

A modality re-sending the same SOP instance (for example after fixing the
accession number) supersedes the earlier copy: the new file replaces it and
deliveries that were not done start again.
"""

import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sop_instance_uid TEXT NOT NULL,
    sop_class_uid TEXT,
    study_instance_uid TEXT,
    series_instance_uid TEXT,
    accession_number TEXT,
    patient_id TEXT,
    patient_name TEXT,
    study_description TEXT,
    modality TEXT,
    calling_ae TEXT,
    peer_ip TEXT,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    received_at REAL NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0,
    file_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_instances_sop ON instances (sop_instance_uid) WHERE superseded = 0;
CREATE INDEX IF NOT EXISTS ix_instances_study ON instances (study_instance_uid);
CREATE INDEX IF NOT EXISTS ix_instances_received ON instances (received_at);

CREATE TABLE IF NOT EXISTS deliveries (
    instance_id INTEGER NOT NULL REFERENCES instances(id),
    destination TEXT NOT NULL,
    state TEXT NOT NULL,           -- pending | sending | done | held | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    first_held_at REAL,
    last_error TEXT,
    last_outcome TEXT,
    updated_at REAL NOT NULL,
    done_at REAL,
    PRIMARY KEY (instance_id, destination)
);
CREATE INDEX IF NOT EXISTS ix_deliveries_due ON deliveries (destination, state, next_attempt_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

OPEN_STATES = ("pending", "sending", "held")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        with self.connect() as db:
            db.executescript(SCHEMA)
            # A crash mid-send leaves rows in "sending": they are due again.
            db.execute("UPDATE deliveries SET state = 'pending' WHERE state = 'sending'")

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")  # a stored image must survive power loss
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def connect(self):
        conn = self._conn()
        yield conn

    @contextmanager
    def transaction(self):
        conn = self._conn()
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ── receiving ─────────────────────────────────────────────────────────

    def add_instance(self, meta: dict, destinations: Iterable[str]) -> tuple[int, str | None]:
        """Record a received instance. Returns (id, path of a superseded file to delete)."""
        now = time.time()
        old_path = None
        with self.transaction() as db:
            old = db.execute(
                "SELECT id, path FROM instances WHERE sop_instance_uid = ? AND superseded = 0",
                (meta["sop_instance_uid"],),
            ).fetchone()
            if old is not None:
                db.execute("UPDATE instances SET superseded = 1 WHERE id = ?", (old["id"],))
                db.execute(
                    "UPDATE deliveries SET state = 'done', last_outcome = 'superseded', updated_at = ? "
                    "WHERE instance_id = ? AND state != 'done'",
                    (now, old["id"]),
                )
                if old["path"] != meta["path"]:
                    old_path = old["path"]
            cur = db.execute(
                """INSERT INTO instances (sop_instance_uid, sop_class_uid, study_instance_uid, series_instance_uid,
                       accession_number, patient_id, patient_name, study_description, modality, calling_ae,
                       peer_ip, path, size, received_at)
                   VALUES (:sop_instance_uid, :sop_class_uid, :study_instance_uid, :series_instance_uid,
                       :accession_number, :patient_id, :patient_name, :study_description, :modality,
                       :calling_ae, :peer_ip, :path, :size, :received_at)""",
                {**meta, "received_at": meta.get("received_at", now)},
            )
            instance_id = cur.lastrowid
            for dest in destinations:
                db.execute(
                    "INSERT INTO deliveries (instance_id, destination, state, updated_at) VALUES (?, ?, 'pending', ?)",
                    (instance_id, dest, now),
                )
        return instance_id, old_path

    def known_paths(self) -> set[str]:
        with self.connect() as db:
            return {r[0] for r in db.execute("SELECT path FROM instances WHERE file_deleted = 0")}

    # ── sending ───────────────────────────────────────────────────────────

    def claim_due(self, destination: str, limit: int, max_bytes: int) -> list[sqlite3.Row]:
        """Mark up to `limit` due deliveries (oldest first, same study first)
        as sending and return them with their instance rows."""
        now = time.time()
        with self.transaction() as db:
            rows = db.execute(
                """SELECT d.instance_id, d.attempts, d.state, d.first_held_at, i.*
                   FROM deliveries d JOIN instances i ON i.id = d.instance_id
                   WHERE d.destination = ? AND d.state IN ('pending', 'held') AND d.next_attempt_at <= ?
                   ORDER BY d.state = 'held', i.received_at, i.id
                   LIMIT ?""",
                (destination, now, limit * 4),
            ).fetchall()
            picked, total = [], 0
            study = rows[0]["study_instance_uid"] if rows else None
            for row in rows:
                if len(picked) >= limit:
                    break
                if picked and (total + row["size"] > max_bytes or row["study_instance_uid"] != study):
                    continue
                picked.append(row)
                total += row["size"]
            for row in picked:
                db.execute(
                    "UPDATE deliveries SET state = 'sending', updated_at = ? WHERE instance_id = ? AND destination = ?",
                    (now, row["instance_id"], destination),
                )
        return picked

    def mark(self, instance_id: int, destination: str, state: str, *, next_attempt_at: float = 0,
             error: str | None = None, outcome: str | None = None, count_attempt: bool = True,
             held_since: float | None = None) -> None:
        now = time.time()
        with self.transaction() as db:
            db.execute(
                """UPDATE deliveries SET state = ?, next_attempt_at = ?, last_error = ?, last_outcome = ?,
                       attempts = attempts + ?, updated_at = ?,
                       done_at = CASE WHEN ? = 'done' THEN ? ELSE done_at END,
                       first_held_at = CASE WHEN ? = 'held' THEN COALESCE(first_held_at, ?) ELSE first_held_at END
                   WHERE instance_id = ? AND destination = ?""",
                (state, next_attempt_at, (error or "")[:500] or None, outcome, 1 if count_attempt else 0, now,
                 state, now, state, held_since or now, instance_id, destination),
            )

    def release_sending(self, destination: str, next_attempt_at: float, error: str) -> None:
        """Put claimed rows back (the destination could not be reached at all),
        without counting an attempt against each image."""
        with self.transaction() as db:
            db.execute(
                "UPDATE deliveries SET state = CASE WHEN first_held_at IS NULL THEN 'pending' ELSE 'held' END, "
                "next_attempt_at = ?, last_error = ?, updated_at = ? WHERE destination = ? AND state = 'sending'",
                (next_attempt_at, error[:500], time.time(), destination),
            )

    def retry(self, *, study_instance_uid: str | None = None, destination: str | None = None,
              states: tuple = ("held", "failed", "pending")) -> int:
        clauses, params = [f"d.state IN ({','.join('?' * len(states))})"], list(states)
        if study_instance_uid:
            clauses.append("i.study_instance_uid = ?")
            params.append(study_instance_uid)
        if destination:
            clauses.append("d.destination = ?")
            params.append(destination)
        with self.transaction() as db:
            cur = db.execute(
                f"""UPDATE deliveries SET next_attempt_at = 0,
                        state = CASE WHEN state = 'failed' THEN 'pending' ELSE state END,
                        first_held_at = CASE WHEN state = 'failed' THEN NULL ELSE first_held_at END
                    WHERE rowid IN (SELECT d.rowid FROM deliveries d JOIN instances i ON i.id = d.instance_id
                                    WHERE {' AND '.join(clauses)} AND i.file_deleted = 0)""",
                params,
            )
            return cur.rowcount

    # ── housekeeping ──────────────────────────────────────────────────────

    def deletable(self, older_than: float, limit: int = 500) -> list[sqlite3.Row]:
        """Files delivered everywhere (or superseded) and received before `older_than`."""
        with self.connect() as db:
            return db.execute(
                """SELECT i.id, i.path FROM instances i
                   WHERE i.file_deleted = 0 AND (i.superseded = 1 OR i.received_at < ?)
                     AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.instance_id = i.id AND d.state != 'done')
                   LIMIT ?""",
                (older_than, limit),
            ).fetchall()

    def mark_file_deleted(self, ids: list[int]) -> None:
        if not ids:
            return
        with self.transaction() as db:
            db.executemany("UPDATE instances SET file_deleted = 1 WHERE id = ?", [(i,) for i in ids])

    def log_event(self, level: str, message: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT INTO events (at, level, message) VALUES (?, ?, ?)", (time.time(), level, message[:1000]))
            db.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 2000 FROM events)")

    # ── reporting ─────────────────────────────────────────────────────────

    def counts(self) -> dict:
        with self.connect() as db:
            rows = db.execute("SELECT destination, state, COUNT(*) AS n FROM deliveries "
                              "WHERE state != 'done' GROUP BY destination, state").fetchall()
            today = db.execute("SELECT COUNT(*) FROM instances WHERE received_at >= ? AND superseded = 0",
                               (time.time() - 86400,)).fetchone()[0]
            on_disk = db.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM instances WHERE file_deleted = 0").fetchone()
        by_dest: dict = {}
        for r in rows:
            by_dest.setdefault(r["destination"], {})[r["state"]] = r["n"]
        totals = {s: sum(d.get(s, 0) for d in by_dest.values()) for s in ("pending", "sending", "held", "failed")}
        return {"by_destination": by_dest, "totals": totals, "received_24h": today,
                "files_on_disk": on_disk[0], "bytes_on_disk": on_disk[1]}

    def recent_studies(self, limit: int = 50, problems_only: bool = False) -> list[dict]:
        having = "HAVING SUM(d.state IN ('held','failed')) > 0" if problems_only else ""
        with self.connect() as db:
            studies = db.execute(
                f"""SELECT i.study_instance_uid, MAX(i.patient_name) AS patient_name, MAX(i.patient_id) AS patient_id,
                           MAX(i.accession_number) AS accession_number, MAX(i.modality) AS modality,
                           MAX(i.study_description) AS study_description, MAX(i.calling_ae) AS calling_ae,
                           MIN(i.received_at) AS first_received, MAX(i.received_at) AS last_received,
                           COUNT(DISTINCT i.id) AS instances
                    FROM instances i JOIN deliveries d ON d.instance_id = i.id
                    WHERE i.superseded = 0
                    GROUP BY i.study_instance_uid {having}
                    ORDER BY last_received DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for s in studies:
                states = db.execute(
                    """SELECT d.destination, d.state, COUNT(*) AS n, MAX(d.last_error) AS last_error,
                              MAX(d.last_outcome) AS last_outcome
                       FROM deliveries d JOIN instances i ON i.id = d.instance_id
                       WHERE i.study_instance_uid IS ? AND i.superseded = 0
                       GROUP BY d.destination, d.state""",
                    (s["study_instance_uid"],),
                ).fetchall()
                dests: dict = {}
                for st in states:
                    entry = dests.setdefault(st["destination"], {"counts": {}, "last_error": None})
                    entry["counts"][st["state"]] = st["n"]
                    if st["state"] != "done" and st["last_error"]:
                        entry["last_error"] = st["last_error"]
                result.append({**dict(s), "destinations": dests})
            return result

    def events(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT at, level, message FROM events ORDER BY id DESC LIMIT ?", (limit,))]


def fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return  # not supported on Windows; NTFS journals the rename
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
