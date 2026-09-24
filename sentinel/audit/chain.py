"""Hash-chained JSON Lines.

Each line is a canonical JSON object carrying seq, the previous line's
hash, and its own hash over everything else. Editing or removing a line
breaks every hash after it, so `verify` finds the first bad line.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import threading
from typing import Any

GENESIS = "0" * 64


@dataclasses.dataclass(frozen=True)
class VerifyResult:
    ok: bool
    count: int
    first_bad: int | None = None


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _digest(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: pathlib.Path | None):
        self._path = path
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        if path is not None and path.exists():
            self._entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def append(self, record: dict[str, Any], at: str) -> dict[str, Any]:
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else GENESIS
            entry = {**record, "seq": len(self._entries), "at": at, "prev": prev}
            entry["hash"] = _digest(entry)
            self._entries.append(entry)
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a") as f:
                    f.write(_canonical(entry) + "\n")
            return entry

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def verify(self) -> VerifyResult:
        prev = GENESIS
        for index, entry in enumerate(self._entries):
            if entry.get("seq") != index or entry.get("prev") != prev or entry.get("hash") != _digest(entry):
                return VerifyResult(False, len(self._entries), index)
            prev = entry["hash"]
        return VerifyResult(True, len(self._entries))
