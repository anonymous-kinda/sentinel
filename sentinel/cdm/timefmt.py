"""CCSDS ASCII time codes, as used in CDM keyword values.

CCSDS 301.0-B-4 allows two calendar forms and CDMs use both in practice:

    ASCII Time Code A   YYYY-MM-DDThh:mm:ss[.d...][Z]
    ASCII Time Code B   YYYY-DDDThh:mm:ss[.d...][Z]    (day of year)

NASA CARA's own sample CDMs carry CREATION_DATE in form B
(e.g. ``2017-225T22:16:40.000``) and TCA in either form, so a parser
that accepts only form A would reject real messages.

Times are UTC. Sub-microsecond digits are truncated, not rounded: Python's
datetime has microsecond resolution, and the CDM TCA is itself already
rounded to the millisecond upstream (which the risk engine corrects for by
refining TCA from the states - see risk/encounter.py).
"""

from __future__ import annotations

import datetime as _dt
import re

_UTC = _dt.UTC

_CALENDAR = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})T"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})(?:\.(?P<frac>\d+))?Z?$"
)
_ORDINAL = re.compile(
    r"^(?P<y>\d{4})-(?P<doy>\d{3})T"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})(?:\.(?P<frac>\d+))?Z?$"
)


def _micro(frac: str | None) -> int:
    if not frac:
        return 0
    return int((frac + "000000")[:6])


def parse_ccsds_time(text: str) -> _dt.datetime:
    """Parse a CCSDS ASCII time (form A or B) into an aware UTC datetime.

    Raises ValueError on anything else. A timestamp that cannot be read is
    load-bearing for a TCA, so failing loudly is correct here.
    """
    value = text.strip()
    m = _CALENDAR.match(value)
    if m:
        return _dt.datetime(
            int(m["y"]), int(m["mo"]), int(m["d"]),
            int(m["h"]), int(m["mi"]), int(m["s"]), _micro(m["frac"]),
            tzinfo=_UTC,
        )
    m = _ORDINAL.match(value)
    if m:
        day_of_year = int(m["doy"])
        if not 1 <= day_of_year <= 366:
            raise ValueError(f"day of year out of range in CCSDS time {text!r}")
        base = _dt.datetime(int(m["y"]), 1, 1, tzinfo=_UTC)
        try:
            return base + _dt.timedelta(
                days=day_of_year - 1,
                hours=int(m["h"]),
                minutes=int(m["mi"]),
                seconds=int(m["s"]),
                microseconds=_micro(m["frac"]),
            )
        except OverflowError as exc:
            raise ValueError(f"CCSDS time beyond the year 9999: {text!r}") from exc
    raise ValueError(f"not a CCSDS ASCII time: {text!r}")


def format_ccsds_time(when: _dt.datetime) -> str:
    """Format as CCSDS ASCII Time Code A with millisecond precision."""
    if when.tzinfo is None:
        raise ValueError("refusing to format a naive datetime; CDM times are UTC")
    utc = when.astimezone(_UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}"
