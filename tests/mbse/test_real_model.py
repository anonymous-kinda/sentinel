"""The model in mbse/, traced against this repository.

Runs `pytest --collect-only` in a subprocess (offline, about 3 s) so that
every test id the model names is checked against what pytest would run.
"""

import pathlib

import pytest

from mbse.generate import collect_pytest, generate
from mbse.trace import Status, render_markdown

ROOT = pathlib.Path(__file__).resolve().parents[2]
AREAS = {"DEP", "MOSA", "DDIL", "RISK", "AI", "OPSEC", "PASS", "SC"}


@pytest.fixture(scope="module")
def trace():
    return generate(ROOT, collect_pytest(ROOT))


def test_the_model_has_no_broken_references(trace):
    assert trace.problems == ()
    assert [row.requirement.id for row in trace.rows if row.status is Status.BROKEN] == []


def test_the_committed_trace_is_current(trace):
    committed = (ROOT / "docs" / "traceability.md").read_text(encoding="utf-8")
    assert committed == render_markdown(trace), "docs/traceability.md is stale: run `make trace`"


def test_every_requirement_is_satisfied_by_a_part_and_has_a_verification_case(trace):
    assert [row.requirement.id for row in trace.rows if not row.satisfied_by] == []
    assert [row.requirement.id for row in trace.rows if not row.evidence] == []


def test_unverified_means_planned_never_forgotten(trace):
    for row in trace.rows:
        if row.status is Status.UNVERIFIED:
            assert any(link.planned for link in row.evidence), row.requirement.id


def test_every_area_the_role_names_is_modelled_and_verified_somewhere(trace):
    assert {row.area for row in trace.rows} == AREAS
    verified = {row.area for row in trace.rows if row.status is Status.VERIFIED}
    assert verified == AREAS, "every area has at least one requirement with evidence"
