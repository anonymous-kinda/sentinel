"""A quarantined CDM is logged, not only stored, published and answered.

An operator watching the node's log (journald, Elastic) sees each one under
one stable message, with its code, its sha256 and where it came from, and
never its content: a CDM's text is data, not a log line.
"""

import asyncio
import datetime as dt
import logging

import pytest

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore

from ..test_cdm_codec import OPERATIONAL, _replace

NOW = dt.datetime(2026, 9, 23, 12, tzinfo=dt.UTC)
MARKER = "SECRET-PAYLOAD-7f3a"
QUARANTINED = {
    "parse-error": f"{MARKER}\n".encode(),
    "wrong-frame": _replace(OPERATIONAL.read_text(), "REF_FRAME", f"REF_FRAME = {MARKER}").encode(),
}


def ingest(raw: bytes, source: str = "api-upload"):
    service = ConjunctionService(ConjunctionStore(":memory:"), InProcessBus(), FixedClock(NOW))
    return asyncio.run(service.ingest(raw, source, "REAL"))


def quarantine_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "CDM quarantined"]


@pytest.mark.parametrize("raw", QUARANTINED.values(), ids=QUARANTINED.keys())
def test_a_quarantine_is_logged_with_its_code_hash_and_source_and_never_its_content(caplog, raw):
    with caplog.at_level(logging.WARNING, logger="sentinel.conjunction.service"):
        result = ingest(raw)
    assert result.status == "rejected"
    [record] = quarantine_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.fields == {"code": result.code, "sha256": result.sha256, "source": "api-upload"}
    assert MARKER not in caplog.text


def test_an_accepted_cdm_logs_no_quarantine(caplog):
    with caplog.at_level(logging.WARNING, logger="sentinel.conjunction.service"):
        assert ingest(OPERATIONAL.read_bytes()).status == "accepted"
    assert quarantine_records(caplog) == []
