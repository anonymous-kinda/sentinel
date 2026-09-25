"""CDMs for conjunction-service tests, and a service to ingest them into.

Every CDM here starts as the exercise scenario's first message (EX-RED:
EXSAT-1 x EX-DEB 118, TCA 2026-09-24T07:00:00, both covariances, HBR in a
COMMENT) and is changed one KVN line at a time, so each test states exactly
how its message differs from a message the engine is validated on.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.risk.types import AssessmentConfig

EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
NOW = EPOCH + dt.timedelta(minutes=1)
COVARIANCE_LINE = re.compile(r"^(C(R|T|N|RDOT|TDOT|NDOT|DRG|SRP)_\w+|COVARIANCE_METHOD)\s*=", re.MULTILINE)


def first_exercise_kvn() -> str:
    return generate(EPOCH)[0].kvn


def edited(kvn: str, **fields: str) -> str:
    """The same message with each named header line's value replaced."""
    for key, value in fields.items():
        kvn, count = re.subn(rf"^{key}(\s*)= .*$", rf"{key}\g<1>= {value}", kvn, count=1, flags=re.MULTILINE)
        assert count == 1, f"{key} is not a line of this message"
    return kvn


def without_covariance(kvn: str) -> str:
    """As a screening CDM is filed: geometry only (sentinel/screening/derived_cdm.py)."""
    return "\n".join(line for line in kvn.splitlines() if not COVARIANCE_LINE.match(line)) + "\n"


def without_hbr(kvn: str) -> str:
    """No combined HBR COMMENT and no areas: the engine needs its configured default radius."""
    return "\n".join(line for line in kvn.splitlines() if not line.startswith("COMMENT HBR")) + "\n"


def without_creation_date(kvn: str) -> str:
    """Admitted: the profile then orders the event's CDMs by time of receipt."""
    return "\n".join(line for line in kvn.splitlines() if not line.startswith("CREATION_DATE")) + "\n"


def real_kvn() -> str:
    """The first exercise message, as if an operations centre had sent it."""
    return edited(first_exercise_kvn(), ORIGINATOR="TEST-OPS-CENTRE")


def make_service(
    node_id: str = "standalone", config: AssessmentConfig | None = None, clock: FixedClock | None = None
) -> ConjunctionService:
    return ConjunctionService(
        ConjunctionStore(), InProcessBus(), clock or FixedClock(NOW), engine_config=config, node_id=node_id
    )


def run(coro):
    return asyncio.run(coro)
