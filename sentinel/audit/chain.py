"""Hash-chained JSON Lines.

Each line is a canonical JSON object carrying seq, the previous line's
hash, and its own hash over everything else. Editing or removing a line
breaks every hash after it, so `verify` finds the first bad line.

The file is the record. `verify` and `entries` read it every time, and
`verify` also holds it against the hashes this process has seen and
written, so an edit, a deletion or a truncation made while the node runs
is found at its line. A truncation made while the node is down is not
(AU-9 in SECURITY.md).

A line that cannot be read - a write torn by a power cut, or bytes that
are not a JSON object - breaks the chain at that line; it never stops the
node. Appending goes on after it, because the assistant's asks and
confirms must still be recorded: the torn bytes stay on their own line as
evidence, the next entry links to the last readable one, and `verify`
reports the break at the torn line from then on. The chain never verifies
over it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import threading
from typing import IO, Any

from ..obs import get_logger

log = get_logger(__name__)

GENESIS = "0" * 64

Record = dict[str, Any]


@dataclasses.dataclass(frozen=True)
class VerifyResult:
    ok: bool
    count: int
    first_bad: int | None = None


def _canonical(record: Record) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _digest(record: Record) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


def _parse(line: bytes) -> Record | None:
    """One line as a record, or None when it cannot be read as one."""
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):  # includes JSONDecodeError and UnicodeDecodeError
        return None
    return record if isinstance(record, dict) else None


def _hash_of(record: Record | None) -> str | None:
    value = None if record is None else record.get("hash")
    return value if isinstance(value, str) else None


def _links(record: Record, seq: int, prev: str) -> bool:
    return record.get("seq") == seq and record.get("prev") == prev and record.get("hash") == _digest(record)


def _first_bad(records: list[Record | None], known: list[str | None]) -> int | None:
    """The first line that cannot be read, does not link, or is not the line
    this process knows at that position; or where the file ends before the
    lines it knows. None when the chain is whole."""
    prev = GENESIS
    for seq, record in enumerate(records):
        if record is None or not _links(record, seq, prev):
            return seq
        if seq < len(known) and record["hash"] != known[seq]:
            return seq
        prev = record["hash"]
    return len(records) if len(records) < len(known) else None


class _MemoryLines:
    """The chain's lines in memory only: tests and ephemeral nodes."""

    def __init__(self) -> None:
        self._lines: list[bytes] = []

    def read(self) -> list[bytes]:
        return list(self._lines)

    def append(self, line: bytes) -> None:
        self._lines.append(line)


class _FileLines:
    """The chain's lines in a JSON Lines file."""

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def read(self) -> list[bytes]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        return [line for line in raw.split(b"\n") if line.strip()]

    def append(self, line: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+b") as f:
            _end_a_torn_line(f)
            f.write(line + b"\n")


def _end_a_torn_line(f: IO[bytes]) -> None:
    """A write cut off mid-line leaves the file without a final newline. End
    that line, keeping its bytes, so the next entry starts a line of its own."""
    size = f.seek(0, os.SEEK_END)
    if size:
        f.seek(size - 1)
        if f.read(1) != b"\n":
            f.write(b"\n")


class AuditLog:
    def __init__(self, path: pathlib.Path | None):
        self._lines = _FileLines(path) if path is not None else _MemoryLines()
        self._lock = threading.Lock()
        self._reported_bad: int | None = None
        # The hash at each line as this process loaded or wrote it; None for a
        # line it could not read. It is what `verify` holds the file against.
        self._known: list[str | None] = [_hash_of(record) for record in self._records()]
        self.verify()

    def append(self, record: Record, at: str) -> Record:
        with self._lock:
            prev = next((h for h in reversed(self._known) if h is not None), GENESIS)
            entry = {**record, "seq": len(self._known), "at": at, "prev": prev}
            entry["hash"] = _digest(entry)
            self._lines.append(_canonical(entry).encode())
            self._known.append(entry["hash"])
            return entry

    def entries(self) -> list[Record]:
        """Every readable line of the record, oldest first."""
        with self._lock:
            return [record for record in self._records() if record is not None]

    def verify(self) -> VerifyResult:
        """Walk the record as it is now, and name the first line that breaks it."""
        with self._lock:
            records = self._records()
            first_bad = _first_bad(records, self._known)
            result = VerifyResult(first_bad is None, len(records), first_bad)
            self._report(result)
        return result

    def _records(self) -> list[Record | None]:
        return [_parse(line) for line in self._lines.read()]

    def _report(self, result: VerifyResult) -> None:
        """Log a break once when found, not on every verify that sees it again."""
        if result.ok:
            self._reported_bad = None
        elif result.first_bad != self._reported_bad:
            self._reported_bad = result.first_bad
            log.error("Audit chain broken", first_bad=result.first_bad, count=result.count)
