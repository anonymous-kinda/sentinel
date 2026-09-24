"""SQLite projection of received CDMs and their assessments.

The raw CDM bytes are the source of truth. Everything else in this store -
event grouping, assessments - is derived from them and can be rebuilt by
replaying the raw messages (`rebuild`). An assessment is cached per engine
version, so upgrading the engine re-assesses rather than trusting numbers
an older engine produced.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS cdm_messages (
    sha256        TEXT PRIMARY KEY,
    raw           BLOB NOT NULL,
    message_id    TEXT,
    originator    TEXT,
    creation_date TEXT,
    tca           TEXT NOT NULL,
    primary_id    TEXT NOT NULL,
    secondary_id  TEXT NOT NULL,
    event_id      TEXT NOT NULL,
    data_class    TEXT NOT NULL,
    source        TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    warnings      TEXT NOT NULL,
    hbr_source    TEXT
);
CREATE INDEX IF NOT EXISTS cdm_event ON cdm_messages(event_id, creation_date);

CREATE TABLE IF NOT EXISTS events (
    event_id       TEXT PRIMARY KEY,
    primary_id     TEXT NOT NULL,
    primary_name   TEXT,
    secondary_id   TEXT NOT NULL,
    secondary_name TEXT,
    tca_ref        TEXT NOT NULL,
    data_class     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_pair ON events(primary_id, secondary_id);

CREATE TABLE IF NOT EXISTS assessments (
    sha256         TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    result         TEXT NOT NULL,
    assessed_at    TEXT NOT NULL,
    PRIMARY KEY (sha256, engine_version)
);

CREATE TABLE IF NOT EXISTS quarantine (
    sha256      TEXT PRIMARY KEY,
    raw         BLOB NOT NULL,
    code        TEXT NOT NULL,
    detail      TEXT NOT NULL,
    source      TEXT NOT NULL,
    received_at TEXT NOT NULL
);
"""


@dataclasses.dataclass(frozen=True)
class CdmRow:
    sha256: str
    raw: bytes
    message_id: str | None
    originator: str | None
    creation_date: str | None
    tca: str
    primary_id: str
    secondary_id: str
    event_id: str
    data_class: str
    source: str
    received_at: str
    warnings: list[dict]
    hbr_source: str | None


@dataclasses.dataclass(frozen=True)
class EventRow:
    event_id: str
    primary_id: str
    primary_name: str | None
    secondary_id: str
    secondary_name: str | None
    tca_ref: str
    data_class: str


class ConjunctionStore:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)

    # --- raw messages -------------------------------------------------------
    def has_cdm(self, sha256: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM cdm_messages WHERE sha256=?", (sha256,)).fetchone() is not None

    def add_cdm(self, row: CdmRow) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO cdm_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row.sha256, row.raw, row.message_id, row.originator, row.creation_date,
                    row.tca, row.primary_id, row.secondary_id, row.event_id, row.data_class,
                    row.source, row.received_at, json.dumps(row.warnings), row.hbr_source,
                ),
            )

    def cdms_for_event(self, event_id: str) -> list[CdmRow]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM cdm_messages WHERE event_id=? "
                "ORDER BY COALESCE(creation_date, received_at), received_at",
                (event_id,),
            ).fetchall()
        return [self._cdm(r) for r in rows]

    def all_cdms(self) -> Iterator[CdmRow]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM cdm_messages ORDER BY received_at").fetchall()
        for r in rows:
            yield self._cdm(r)

    def cdm(self, sha256: str) -> CdmRow | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM cdm_messages WHERE sha256=?", (sha256,)).fetchone()
        return None if r is None else self._cdm(r)

    @staticmethod
    def _cdm(r: sqlite3.Row) -> CdmRow:
        return CdmRow(
            sha256=r["sha256"], raw=bytes(r["raw"]), message_id=r["message_id"],
            originator=r["originator"], creation_date=r["creation_date"], tca=r["tca"],
            primary_id=r["primary_id"], secondary_id=r["secondary_id"], event_id=r["event_id"],
            data_class=r["data_class"], source=r["source"], received_at=r["received_at"],
            warnings=json.loads(r["warnings"]), hbr_source=r["hbr_source"],
        )

    # --- events -------------------------------------------------------------
    def events_for_pair(self, primary_id: str, secondary_id: str) -> list[EventRow]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM events WHERE primary_id=? AND secondary_id=?",
                (primary_id, secondary_id),
            ).fetchall()
        return [EventRow(**dict(r)) for r in rows]

    def add_event(self, row: EventRow) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?)",
                dataclasses.astuple(row),
            )

    def event(self, event_id: str) -> EventRow | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return None if r is None else EventRow(**dict(r))

    def events(self) -> list[EventRow]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM events").fetchall()
        return [EventRow(**dict(r)) for r in rows]

    # --- assessments ----------------------------------------------------------
    def assessment(self, sha256: str, engine_version: str) -> dict | None:
        with self._lock:
            r = self._db.execute(
                "SELECT result FROM assessments WHERE sha256=? AND engine_version=?",
                (sha256, engine_version),
            ).fetchone()
        return None if r is None else json.loads(r["result"])

    def put_assessment(self, sha256: str, engine_version: str, result: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO assessments VALUES (?,?,?,?)",
                (sha256, engine_version, json.dumps(result), _now()),
            )

    # --- quarantine -----------------------------------------------------------
    def quarantine(self, sha256: str, raw: bytes, code: str, detail: str, source: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO quarantine VALUES (?,?,?,?,?,?)",
                (sha256, raw, code, detail, source, _now()),
            )

    def quarantined(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT sha256, code, detail, source, received_at FROM quarantine ORDER BY received_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_derived(self) -> None:
        """Drop everything derivable from raw messages (for rebuild)."""
        with self._lock:
            self._db.executescript("DELETE FROM events; DELETE FROM assessments;")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
