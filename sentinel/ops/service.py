"""Operator data: the decision log and per-event annotations.

Persisted in SQLite and replicated by state-based anti-entropy
(`exchange_payload` / `merge_payload`). The CRDT state is itself durable,
so a node that is denied for six hours loses nothing: it keeps writing
locally, and on reconnect one exchange brings both sides to the same state.

This module is mission-agnostic. It knows event ids as opaque strings. Whether a
decision is still current - REVIEW_REQUIRED when it was made against a
CDM that has since been superseded - is answered by a callback the
mission module supplies (`current_ref`).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from ..bus import Bus, subjects
from ..clock import Clock
from ..crdt import DotContext, NodeKey, SignedLog, TrustStore, codec
from ..crdt.log import Entry
from ..crdt.mvmap import MVMap, Register
from ..obs import get_logger

log = get_logger(__name__)

ANNOTATION_FIELDS = ("triage_status", "assignee", "note")
ANNOTATION_VALUE_KEYS = frozenset({"v", "by", "node", "at"})
TRIAGE_STATUSES = ("NEW", "WATCH", "MANEUVER_PLANNING", "NO_ACTION", "CLOSED")
DECISIONS = ("MANEUVER", "NO_MANEUVER", "MONITOR", "REQUEST_TASKING")
# The log entries operator data writes: a decision (from an operator, or an
# AI draft an operator confirmed, ADR-007), a note, and the resolution of a
# conflicted annotation (ADR-005). The signed log itself admits these.
ENTRY_KINDS = ("DECISION", "NOTE", "RESOLUTION")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_entries (node TEXT, seq INTEGER, blob BLOB, PRIMARY KEY (node, seq));
CREATE TABLE IF NOT EXISTS ops_registers (key TEXT PRIMARY KEY, blob BLOB);
CREATE TABLE IF NOT EXISTS ops_peers (peer TEXT PRIMARY KEY, blob BLOB);
"""


class OpsService:
    def __init__(
        self,
        node_id: str,
        key: NodeKey,
        trust: TrustStore,
        bus: Bus,
        clock: Clock,
        db_path: str = ":memory:",
        current_ref: Callable[[str], dict | None] | None = None,
    ):
        self.node_id = node_id
        self.bus = bus
        self.clock = clock
        self.log = SignedLog(node_id, key, trust)
        self.mv = MVMap(node_id)
        self.current_ref = current_ref or (lambda _event_id: None)
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self._db.executescript(SCHEMA)
        self._load()

    # --------------------------------------------------------------- persistence
    def _load(self) -> None:
        with self._lock:
            for (blob,) in self._db.execute("SELECT blob FROM ops_entries ORDER BY node, seq"):
                entry = Entry.from_wire(codec.decode(blob))
                self.log.entries[entry.dot] = entry
                self.log.ctx.add(entry.dot)
                self.log.lamport = max(self.log.lamport, entry.lamport)
            for key, blob in self._db.execute("SELECT key, blob FROM ops_registers"):
                reg = Register.from_wire(codec.decode(blob))
                self.mv.registers[key] = reg
                self.mv.ctx.merge(reg.ctx)

    def _save_entries(self, entries: list[Entry]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT OR IGNORE INTO ops_entries VALUES (?,?,?)",
                [(e.dot.node, e.dot.seq, codec.encode(e.to_wire())) for e in entries],
            )

    def _save_register(self, key: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO ops_registers VALUES (?,?)",
                (key, codec.encode(self.mv.registers[key].to_wire())),
            )

    async def _changed(self, what: str, event_id: str | None) -> None:
        await self.bus.publish(
            subjects.local(self.node_id, "ops.changed"),
            json.dumps({"what": what, "event_id": event_id}).encode(),
            {"Sentinel-Kind": "ops.changed"},
        )

    # -------------------------------------------------------------------- writes
    async def append(
        self, event_id: str, kind: str, body: dict, author: str, event_ref: dict | None = None
    ) -> dict:
        if kind not in ENTRY_KINDS:
            raise ValueError(f"log entry kind must be one of {ENTRY_KINDS}, not {kind!r}")
        ref = {"event_id": event_id, **(event_ref or self.current_ref(event_id) or {})}
        entry = self.log.append(kind, body, ref, author, self.clock.now().isoformat())
        self._save_entries([entry])
        await self._changed("log", event_id)
        return self._entry_view(entry)

    async def annotate(self, event_id: str, field: str, value: Any, author: str) -> dict:
        """Write an annotation. A write over a CONFLICT supersedes every
        concurrent value, and appends a RESOLUTION entry saying so (ADR-005)."""
        if field not in ANNOTATION_FIELDS:
            raise ValueError(f"unknown annotation field {field!r}")
        if field == "triage_status" and value not in TRIAGE_STATUSES:
            raise ValueError(f"triage_status must be one of {TRIAGE_STATUSES}")
        key = f"{event_id}|{field}"
        superseded = self._values(key)
        self.mv.write(key, {"v": value, "by": author, "node": self.node_id, "at": self.clock.now().isoformat()})
        self._save_register(key)
        if len(superseded) > 1:
            body = {"field": field, "value": value, "superseded": superseded}
            await self.append(event_id, "RESOLUTION", body, author)
        await self._changed("annotation", event_id)
        return self.annotations(event_id)

    # --------------------------------------------------------------------- views
    def _entry_view(self, entry: Entry) -> dict:
        current = self.current_ref(entry.event_ref.get("event_id", ""))
        superseded = bool(
            current
            and entry.event_ref.get("cdm_sha256")
            and not same_record(current.get("cdm_sha256"), entry.event_ref.get("cdm_sha256"))
        )
        return {
            "dot": [entry.dot.node, entry.dot.seq],
            "lamport": entry.lamport,
            "wall_time": entry.wall_time,
            "kind": entry.kind,
            "event_ref": entry.event_ref,
            "body": entry.body,
            "author": entry.author,
            "node": entry.dot.node,
            "signature_valid": self.log.verify(entry),
            "digest": entry.digest(),
            "review_required": entry.kind == "DECISION" and superseded,
        }

    def entries(self, event_id: str | None = None) -> list[dict]:
        return [
            self._entry_view(e)
            for e in self.log.ordered()
            if event_id is None or e.event_ref.get("event_id") == event_id
        ]

    def _values(self, key: str) -> list[dict]:
        """A register's visible values, each with the dot that wrote it."""
        return [{"dot": [d.node, d.seq], **v} for d, v in self.mv.read(key)]

    def annotations(self, event_id: str) -> dict:
        out = {}
        for field in ANNOTATION_FIELDS:
            values = self._values(f"{event_id}|{field}")
            out[field] = {"values": values, "conflict": len(values) > 1}
        return out

    def conflicts(self) -> list[dict]:
        out = []
        for key in self.mv.registers:
            if self.mv.conflicted(key):
                event_id, field = key.split("|", 1)
                out.append({"event_id": event_id, "field": field})
        return out

    def digest(self) -> dict:
        return {
            "log": self.log.state_digest(),
            "annotations": self.mv.state_digest(),
            "entries": len(self.log.entries),
            "registers": len(self.mv.registers),
            "log_vv": dict(self.log.ctx.vv),
            "mv_vv": dict(self.mv.ctx.vv),
        }

    # ------------------------------------------------------------- anti-entropy
    def contexts(self) -> dict:
        return {"log_ctx": self.log.ctx.to_wire(), "mv_ctx": self.mv.ctx.to_wire()}

    def payload_for(self, log_ctx: dict, mv_ctx: dict) -> dict:
        """Everything this replica holds that a peer with these contexts lacks."""
        return {
            "log": [e.to_wire() for e in self.log.missing_for(DotContext.from_wire(log_ctx))],
            "reg": {k: r.to_wire() for k, r in self.mv.missing_for(DotContext.from_wire(mv_ctx)).items()},
        }

    async def merge_payload(self, payload: dict) -> dict:
        added = self._merge_entries(payload.get("log", []))
        changed_keys = []
        for key, wire in payload.get("reg", {}).items():
            register = _peer_register(key, wire)
            if register is not None and self.mv.merge_register(key, register):
                self._save_register(key)
                changed_keys.append(key)
        if added or changed_keys:
            events = {e.event_ref.get("event_id") for e in added} | {k.split("|", 1)[0] for k in changed_keys}
            for event_id in events:
                await self._changed("merge", event_id)
        return {"entries_added": len(added), "registers_changed": len(changed_keys)}

    def _merge_entries(self, wires: list) -> list[Entry]:
        """Decode every entry before merging any, so a malformed payload
        merges nothing. A merge that stops part-way (IntegrityError) has
        already taken entries into memory, and peers learn this replica's
        context from memory and never resend them: save those too."""
        incoming = [Entry.from_wire(wire) for wire in wires]
        before = set(self.log.entries)
        try:
            return self.log.merge(incoming)
        finally:
            self._save_entries([e for dot, e in self.log.entries.items() if dot not in before])

    # peer contexts remembered between exchanges (stale is safe: sends more)
    def peer_contexts(self, peer: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT blob FROM ops_peers WHERE peer=?", (peer,)).fetchone()
        if row is None:
            return {"log_ctx": DotContext().to_wire(), "mv_ctx": DotContext().to_wire()}
        return codec.decode(row[0])

    def remember_peer(self, peer: str, contexts: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO ops_peers VALUES (?,?)", (peer, codec.encode(contexts)))


def same_record(a: str | None, b: str | None) -> bool:
    """Two references to one record: each is a full sha256, or the leading
    hex digits a hub's summary carries before the record itself arrives."""
    return bool(a and b and (a.startswith(b) or b.startswith(a)))


def _peer_register(key: object, wire: Any) -> Register | None:
    """A peer's register, or None when this node could not show it: an
    annotation key it does not know, or a value that is not an annotation."""
    try:
        register = Register.from_wire(wire)
    except (KeyError, TypeError, ValueError, IndexError):
        log.warning("Peer register rejected", key=str(key)[:80], reason="malformed")
        return None
    problem = _annotation_problem(key, register)
    if problem is not None:
        log.warning("Peer register rejected", key=str(key)[:80], reason=problem)
        return None
    return register


def _annotation_problem(key: object, register: Register) -> str | None:
    event_id, separator, field = key.partition("|") if isinstance(key, str) else ("", "", "")
    if not (event_id and separator and field in ANNOTATION_FIELDS):
        return "unknown annotation key"
    for value in register.store.values():
        if not isinstance(value, dict) or not value.keys() >= ANNOTATION_VALUE_KEYS:
            return "value is not an annotation"
        if field == "triage_status" and value["v"] not in TRIAGE_STATUSES:
            return "unknown triage status"
    return None


def load_identity(node_id: str, var_dir: pathlib.Path, trust_file: pathlib.Path | None) -> tuple[NodeKey, TrustStore]:
    """This node's signing key (created on first start) and the trust store.

    Without a trust file a node trusts only itself: it can author, but it
    will not merge anyone else's entries until an operator installs one.
    """
    key = NodeKey.load_or_create(node_id, var_dir / "keys" / f"{node_id}.ed25519.pem")
    trust = TrustStore.from_file(trust_file) if trust_file else TrustStore()
    if not trust.trusts(node_id):
        trust.add(node_id, key.public_hex())
    pub = var_dir / "keys" / f"{node_id}.pub"
    pub.write_text(json.dumps({node_id: key.public_hex()}) + "\n")
    return key, trust


def now_iso(clock: Clock) -> str:
    return clock.now().astimezone(dt.UTC).isoformat()


@dataclasses.dataclass(frozen=True)
class ExchangeStats:
    sent_entries: int
    sent_registers: int
    received_entries: int
    received_registers: int
    bytes_out: int
    bytes_in: int
