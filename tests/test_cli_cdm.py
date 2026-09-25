"""`sentinel assess` and `sentinel cdm` judge a CDM exactly as the node does.

The node quarantines a CDM that would make an answer wrong, with a code and
a reason. The CLI used to read the same bytes by another path: bytes that
are not UTF-8, a `COMMENT HBR` that is not a number and an `AREA_PC` that is
not a number each ended in a traceback, and `cdm parse` called the AREA_PC
one clean. The CLI now reports the node's code and reason, exits 2, and
never prints a traceback.
"""

import asyncio
import datetime as dt
import json

import pytest

from sentinel import cli
from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.service import ConjunctionService, IngestResult
from sentinel.conjunction.store import ConjunctionStore

from .test_cdm_codec import ALFANO_01, OPERATIONAL, _replace

NOW = dt.datetime(2026, 9, 23, 12, tzinfo=dt.UTC)
OPERATIONAL_TEXT = OPERATIONAL.read_text()
ALFANO_WITHOUT_HBR = "\n".join(
    line for line in ALFANO_01.read_text().splitlines() if not line.startswith("COMMENT HBR")
) + "\n"

UNREADABLE = {
    "not-utf-8": OPERATIONAL.read_bytes().replace(b"= Covariance", b"= Covari\xe9nce", 1),
    "hbr-comment-1.2.3": _replace(OPERATIONAL_TEXT, "COMMENT HBR", "COMMENT HBR = 1.2.3").encode(),
    "area-pc-abc": _replace(ALFANO_WITHOUT_HBR, "AREA_PC", "AREA_PC = abc [m**2]").encode(),
}
PARITY = {
    "operational": OPERATIONAL.read_bytes(),
    "accepted-with-warnings": ALFANO_01.read_bytes(),
    "not-a-cdm": b"hello, world\n",
    "repeated-keyword": OPERATIONAL_TEXT.replace("TCA ", "TCA = 2021-03-26T00:00:00.000\nTCA ", 1).encode(),
    "itrf-frame": _replace(OPERATIONAL_TEXT, "REF_FRAME", "REF_FRAME = ITRF").encode(),
    **UNREADABLE,
}


def node_verdict(raw: bytes) -> IngestResult:
    service = ConjunctionService(ConjunctionStore(":memory:"), InProcessBus(), FixedClock(NOW))
    return asyncio.run(service.ingest(raw, "test", "REAL"))


@pytest.fixture
def run(tmp_path, capsys):
    """`sentinel <command> FILE` on these bytes: (exit status, stdout, stderr)."""

    def run(raw: bytes, *command: str) -> tuple[int, str, str]:
        path = tmp_path / "message.cdm"
        path.write_bytes(raw)
        status = cli.main([*command, str(path)])
        out, err = capsys.readouterr()
        return status, out, err

    return run


@pytest.mark.parametrize("raw", UNREADABLE.values(), ids=UNREADABLE.keys())
def test_the_node_quarantines_each_as_unreadable_naming_what_it_could_not_read(raw):
    result = node_verdict(raw)
    assert (result.status, result.code) == ("rejected", "UNREADABLE")
    assert result.detail.startswith("UNREADABLE")


def test_an_unreadable_reason_names_the_value():
    assert "COMMENT HBR = 1.2.3" in node_verdict(UNREADABLE["hbr-comment-1.2.3"]).detail
    assert "AREA_PC" in node_verdict(UNREADABLE["area-pc-abc"]).detail
    assert "utf-8" in node_verdict(UNREADABLE["not-utf-8"]).detail


@pytest.mark.parametrize("command", [("assess",), ("assess", "--json"), ("cdm", "parse")])
@pytest.mark.parametrize("raw", UNREADABLE.values(), ids=UNREADABLE.keys())
def test_the_cli_reports_the_nodes_code_and_reason_instead_of_a_traceback(run, command, raw):
    status, out, err = run(raw, *command)
    assert (status, out) == (cli.EXIT_REJECTED, "")
    assert err == f"REJECTED {node_verdict(raw).detail}\n"


def test_cdm_emit_reports_bytes_that_are_not_utf8_instead_of_a_traceback(run):
    status, out, err = run(UNREADABLE["not-utf-8"], "cdm", "emit")
    assert (status, out) == (cli.EXIT_REJECTED, "")
    assert err.startswith("REJECTED UNREADABLE")


@pytest.mark.parametrize("raw", PARITY.values(), ids=PARITY.keys())
def test_cdm_parse_calls_clean_exactly_what_the_node_admits(run, raw):
    result = node_verdict(raw)
    status, out, err = run(raw, "cdm", "parse")
    if result.status == "accepted":
        assert status == cli.EXIT_OK and err == ""
        assert [w["code"] for w in json.loads(out)["warnings"]] == [w["code"] for w in result.warnings]
    else:
        assert (status, out) == (cli.EXIT_REJECTED, "")
        assert err == f"REJECTED {result.detail}\n"
        assert err.startswith(f"REJECTED {result.code}")


def test_assess_still_assesses_what_the_node_admits(run):
    status, out, err = run(OPERATIONAL.read_bytes(), "assess", "--json")
    assert (status, err) == (cli.EXIT_OK, "")
    assert json.loads(out)["hbr_source"] == "cdm_comment_hbr"
