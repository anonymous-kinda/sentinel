"""Element sets held as records: one public OMM object per record.

A record's bytes are the object's canonical JSON, so every node derives
the same sha256 from the same element set. Admission follows the repo's
ingest rule: an element set that would make pass timing wrong (missing or
malformed orbital elements) is rejected with a named reason.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import pathlib

from ..obs import get_logger

log = get_logger(__name__)

SNAPSHOT_NAME = "celestrak-resource-20260924.json"
_REPO_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures"

NUMERIC_FIELDS = (
    "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER",
    "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
)
REQUIRED_FIELDS = ("OBJECT_NAME", "NORAD_CAT_ID", "EPOCH", *NUMERIC_FIELDS)


class ElementRejected(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class ElementRecord:
    norad_id: int
    epoch: dt.datetime
    raw: bytes
    sha256: str
    source: str
    fields: dict


@dataclasses.dataclass(frozen=True)
class AddResult:
    status: str                 # accepted | duplicate | superseded
    sha256: str
    norad_id: int


@dataclasses.dataclass(frozen=True)
class SnapshotLoad:
    accepted: int
    rejected: int


def default_snapshot() -> pathlib.Path:
    """The vendored public CelesTrak snapshot: in a source checkout, or under
    SENTINEL_FIXTURES where a bundle installs its fixtures."""
    return pathlib.Path(os.environ.get("SENTINEL_FIXTURES", _REPO_FIXTURES)) / "omm" / SNAPSHOT_NAME


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def element_epoch(fields: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(fields["EPOCH"]).replace(tzinfo=dt.UTC)


def validate_omm(fields: dict) -> None:
    """Raise ElementRejected unless `fields` is a usable OMM mean-element set."""
    for name in REQUIRED_FIELDS:
        if name not in fields:
            raise ElementRejected("MISSING_FIELD", name)
    if not isinstance(fields["NORAD_CAT_ID"], int):
        raise ElementRejected("INVALID_FIELD", "NORAD_CAT_ID")
    try:
        element_epoch(fields)
    except (TypeError, ValueError) as exc:
        raise ElementRejected("INVALID_FIELD", "EPOCH") from exc
    for name in NUMERIC_FIELDS:
        value = fields[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ElementRejected("INVALID_FIELD", name)
    if fields["MEAN_MOTION"] <= 0 or not 0 <= fields["ECCENTRICITY"] < 1:
        raise ElementRejected("INVALID_FIELD", "MEAN_MOTION/ECCENTRICITY")


class ElementStore:
    """Latest element set per object, plus every record hash ever seen.

    `version` counts accepted element sets: it changes exactly when
    `latest()` does, so a result computed from the store can be cached
    against it."""

    def __init__(self):
        self._latest: dict[int, ElementRecord] = {}
        self._seen: set[str] = set()
        self.version = 0

    def add(self, raw: bytes, source: str) -> AddResult:
        sha = hashlib.sha256(raw).hexdigest()
        try:
            fields = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ElementRejected("PARSE_ERROR", str(exc)) from exc
        if not isinstance(fields, dict):
            raise ElementRejected("PARSE_ERROR", "not a JSON object")
        validate_omm(fields)
        norad_id, epoch = fields["NORAD_CAT_ID"], element_epoch(fields)
        if sha in self._seen:
            return AddResult("duplicate", sha, norad_id)
        self._seen.add(sha)
        current = self._latest.get(norad_id)
        if current is not None and current.epoch >= epoch:
            return AddResult("superseded", sha, norad_id)
        self._latest[norad_id] = ElementRecord(norad_id, epoch, raw, sha, source, fields)
        self.version += 1
        return AddResult("accepted", sha, norad_id)

    def load_snapshot(self, path: pathlib.Path, source: str) -> SnapshotLoad:
        """Admit every object in a CelesTrak OMM JSON array; counts what was
        accepted and what was rejected (each rejection is logged with its code)."""
        accepted = rejected = 0
        for obj in json.loads(path.read_text()):
            try:
                accepted += self.add(canonical_bytes(obj), source).status == "accepted"
            except ElementRejected as exc:
                rejected += 1
                log.warning("Element set rejected", source=source, code=exc.code, norad_id=obj.get("NORAD_CAT_ID"))
        return SnapshotLoad(accepted, rejected)

    def latest(self) -> dict[int, dict]:
        return {norad_id: record.fields for norad_id, record in self._latest.items()}

    def records(self) -> list[ElementRecord]:
        return list(self._latest.values())

    def by_sha_prefix(self, sha16: str) -> ElementRecord | None:
        return next((r for r in self._latest.values() if r.sha256.startswith(sha16)), None)

    def has_seen(self, sha16: str) -> bool:
        return any(sha.startswith(sha16) for sha in self._seen)
