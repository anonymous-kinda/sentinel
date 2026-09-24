"""In-memory model of a CCSDS 508.0-B-1 Conjunction Data Message.

ADR-001 makes the CDM the canonical contract at the seam between ingest and
everything downstream. This model therefore preserves the message rather
than cherry-picking fields from it: every keyword, its unit label, and every
COMMENT line survive a parse/emit round trip, so a message forwarded across
a degraded link is the same message that arrived.

The model is deliberately stringly-typed at the storage layer. Values stay
as the text that was received, and typed accessors convert on read. That
keeps the original bytes recoverable for hashing and forwarding, and it
makes the unit label available at exactly the point a number is used.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import math
import re
from collections.abc import Iterator

from .timefmt import parse_ccsds_time

HEADER_KEYS = frozenset(
    {"CCSDS_CDM_VERS", "CREATION_DATE", "ORIGINATOR", "MESSAGE_FOR", "MESSAGE_ID"}
)

# The six position terms of the RTN covariance, lower triangle, CDM order.
POSITION_COVARIANCE_KEYS = ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N")
STATE_POSITION_KEYS = ("X", "Y", "Z")
STATE_VELOCITY_KEYS = ("X_DOT", "Y_DOT", "Z_DOT")


@dataclasses.dataclass(frozen=True)
class KvnField:
    """One ``KEY = VALUE [unit]`` line."""

    key: str
    value: str
    unit: str | None = None


@dataclasses.dataclass(frozen=True)
class Comment:
    """One ``COMMENT ...`` line, text preserved verbatim."""

    text: str


Entry = KvnField | Comment

_HBR_COMMENT = re.compile(
    r"^\s*HBR\s*=\s*(?P<value>[-+0-9.eE]+|NaN)\s*(?:\[(?P<unit>[^\]]*)\])?\s*$",
    re.IGNORECASE,
)


@dataclasses.dataclass(frozen=True)
class CdmSection:
    """An ordered run of entries: the preamble, or one object block."""

    entries: tuple[Entry, ...]

    def fields(self) -> Iterator[KvnField]:
        for entry in self.entries:
            if isinstance(entry, KvnField):
                yield entry

    def comments(self) -> tuple[str, ...]:
        return tuple(e.text for e in self.entries if isinstance(e, Comment))

    def get(self, key: str) -> KvnField | None:
        for f in self.fields():
            if f.key == key:
                return f
        return None

    def text(self, key: str) -> str | None:
        f = self.get(key)
        return None if f is None else f.value

    def number(self, key: str) -> float | None:
        """The keyword's value as a float; None if absent. NaN stays NaN."""
        f = self.get(key)
        if f is None:
            return None
        return float(f.value)

    def has_finite(self, key: str) -> bool:
        value = self.number(key)
        return value is not None and math.isfinite(value)


@dataclasses.dataclass(frozen=True)
class CdmMessage:
    """A parsed CDM: one preamble section and exactly two object sections."""

    preamble: CdmSection
    objects: tuple[CdmSection, CdmSection]

    # --- header ----------------------------------------------------------
    @property
    def version(self) -> str | None:
        return self.preamble.text("CCSDS_CDM_VERS")

    @property
    def message_id(self) -> str | None:
        return self.preamble.text("MESSAGE_ID")

    @property
    def originator(self) -> str | None:
        return self.preamble.text("ORIGINATOR")

    @property
    def creation_date(self) -> _dt.datetime | None:
        value = self.preamble.text("CREATION_DATE")
        return None if value is None else parse_ccsds_time(value)

    # --- relative metadata -------------------------------------------------
    @property
    def tca(self) -> _dt.datetime:
        value = self.preamble.text("TCA")
        if value is None:
            raise KeyError("TCA")
        return parse_ccsds_time(value)

    @property
    def miss_distance_m(self) -> float | None:
        return self.preamble.number("MISS_DISTANCE")

    @property
    def relative_speed_m_s(self) -> float | None:
        return self.preamble.number("RELATIVE_SPEED")

    @property
    def collision_probability(self) -> float | None:
        """The Pc the *originator* asserted, if any. Never Sentinel's own."""
        return self.preamble.number("COLLISION_PROBABILITY")

    @property
    def collision_probability_method(self) -> str | None:
        return self.preamble.text("COLLISION_PROBABILITY_METHOD")

    def hbr_from_comment_m(self) -> float | None:
        """Combined hard-body radius from a ``COMMENT HBR = ...`` line.

        This is a convention, not part of CCSDS 508.0-B-1: CARA and 19 SDS
        carry data the standard has no keyword for in COMMENT lines. Accepted
        units are metres (explicit or unlabelled, which is how CARA writes
        it). Any other label is ambiguous and is not guessed at.
        """
        for text in self.preamble.comments():
            m = _HBR_COMMENT.match(text)
            if not m:
                continue
            unit = (m["unit"] or "m").strip().lower()
            if unit != "m":
                return None
            value = float(m["value"])
            return value if math.isfinite(value) and value > 0 else None
        return None

    # --- objects -------------------------------------------------------------
    def object_designator(self, index: int) -> str | None:
        return self.objects[index].text("OBJECT_DESIGNATOR")

    def object_name(self, index: int) -> str | None:
        return self.objects[index].text("OBJECT_NAME")
