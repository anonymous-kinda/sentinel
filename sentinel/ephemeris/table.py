"""The StateTable and the admission rules every ephemeris source shares.

Wrong raises (EphemerisRejected, with a stable code):
  a frame that is not Earth-fixed, a time system that is not UTC, epochs
  that do not increase, a number that is not finite, a time with no zone.
  Each would put the satellite in the wrong place or at the wrong time.

Incomplete degrades (EphemerisWarning): the source decides what is merely
missing - for example an OEM without velocities (see oem.py).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re

import numpy as np

# Every ITRF realisation (ITRF-93 ... ITRF2020) differs from the others by
# centimetres - nothing at pass-timing scale - so all are accepted as one
# Earth-fixed frame. Inertial frames (EME2000, GCRF, TEME) would need an
# Earth-rotation transform with EOP data; they are refused, not converted.
_EARTH_FIXED = re.compile(r"^ITRF(-?\d{2}|\d{4})?$", re.IGNORECASE)


class EphemerisRejected(ValueError):
    """The ephemeris would produce a wrong answer. Refuse it."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclasses.dataclass(frozen=True)
class EphemerisWarning:
    """The ephemeris was admitted, but something that limits it is recorded."""

    code: str
    detail: str


def require_earth_fixed(frame: str) -> None:
    if not _EARTH_FIXED.match(frame.strip()):
        raise EphemerisRejected(
            "REF_FRAME_NOT_EARTH_FIXED",
            f"REF_FRAME = {frame!r}; only Earth-fixed ITRF realisations are accepted",
        )


def require_utc(time_system: str) -> None:
    if time_system.strip().upper() != "UTC":
        raise EphemerisRejected(
            "TIME_SYSTEM_NOT_UTC",
            f"TIME_SYSTEM = {time_system!r}; only UTC is accepted",
        )


def _require_aware(when: dt.datetime, what: str) -> None:
    if when.tzinfo is None:
        raise EphemerisRejected("NAIVE_TIME", f"{what} has no time zone; refusing to guess")


@dataclasses.dataclass(frozen=True, eq=False)
class StateTable:
    """Earth-fixed (ITRF) positions of one object at strictly increasing UTC epochs.

    `created` is when the ephemeris product was made (an OEM's CREATION_DATE);
    the pass provider reports each window's age relative to it.
    """

    norad_id: int
    name: str
    epochs: tuple[dt.datetime, ...]
    positions_km: np.ndarray
    created: dt.datetime

    def __post_init__(self) -> None:
        positions = np.array(self.positions_km, dtype=float)
        if positions.ndim != 2 or positions.shape != (len(self.epochs), 3):
            raise EphemerisRejected(
                "SHAPE_MISMATCH",
                f"positions shape {positions.shape} does not match {len(self.epochs)} epochs x 3",
            )
        if len(self.epochs) < 2:
            raise EphemerisRejected("TOO_FEW_STATES", f"{len(self.epochs)} state(s); a table needs a span")
        if not np.isfinite(positions).all():
            raise EphemerisRejected("MALFORMED_NUMBER", "a position is not finite")
        _require_aware(self.created, "created")
        for index, epoch in enumerate(self.epochs):
            _require_aware(epoch, f"epoch {index}")
        for index, (earlier, later) in enumerate(zip(self.epochs, self.epochs[1:]), start=1):
            if later <= earlier:
                raise EphemerisRejected(
                    "EPOCHS_NOT_INCREASING",
                    f"epoch {index} ({later.isoformat()}) does not follow {earlier.isoformat()}",
                )
        positions.flags.writeable = False
        object.__setattr__(self, "positions_km", positions)
        object.__setattr__(self, "epochs", tuple(self.epochs))

    @property
    def start(self) -> dt.datetime:
        return self.epochs[0]

    @property
    def stop(self) -> dt.datetime:
        return self.epochs[-1]
