"""Requirement -> satisfied by -> verified by -> status.

The status is conservative. A requirement is verified only when it has at
least one verification case, none of its cases is planned, and every piece of
evidence they name resolves. Evidence that does not exist and is not planned
is a broken reference, and the trace is not ok.
"""

import pytest

from mbse.sysml import Evidence, Model, Requirement, Satisfy, VerificationCase
from mbse.trace import Status, build_trace, render_markdown


class Known:
    """An evidence index that knows a fixed set of locators."""

    def __init__(self, *locators):
        self.locators = set(locators)

    def resolves(self, locator):
        return locator in self.locators


INDEXES = {"pytest": Known("tests/a.py::test_a", "tests/b.py::test_b"), "harness": Known("DENIED")}
PARTS = frozenset({"sentinel", "edge", "hub", "console", "a", "z", "part"})


def req(rid, name, text="Text."):
    return Requirement(rid, name, text)


def case(vid, *verifies, evidence=(), planned=None, reason=""):
    return VerificationCase(vid, f"vc{vid}", verifies, tuple(evidence), planned, reason)


def pytest_evidence(locator):
    return Evidence("pytest", locator)


def status_of(trace, rid):
    return next(row.status for row in trace.rows if row.requirement.id == rid)


def test_all_evidence_resolving_is_verified():
    model = Model(
        (req("REQ-DDIL-001", "a"),),
        (Satisfy("a", "sentinel.edge.console"),),
        (case("VC-1", "a", evidence=[pytest_evidence("tests/a.py::test_a"), Evidence("harness", "DENIED")]),),
        PARTS,
    )
    trace = build_trace(model, INDEXES)
    assert status_of(trace, "REQ-DDIL-001") is Status.VERIFIED
    assert trace.ok


def test_no_verification_case_is_unverified_not_an_error():
    trace = build_trace(Model((req("REQ-X-001", "a"),), (), ()), INDEXES)
    assert status_of(trace, "REQ-X-001") is Status.UNVERIFIED
    assert trace.ok


def test_planned_evidence_is_unverified_even_if_other_evidence_resolves():
    model = Model(
        (req("REQ-X-001", "a"),),
        (),
        (
            case("VC-1", "a", evidence=[pytest_evidence("tests/a.py::test_a")]),
            case("VC-2", "a", evidence=[pytest_evidence("tests/not/yet.py::test_it")], planned="M3"),
        ),
    )
    trace = build_trace(model, INDEXES)
    assert status_of(trace, "REQ-X-001") is Status.UNVERIFIED
    assert trace.ok


@pytest.mark.parametrize(
    "evidence",
    [
        [pytest_evidence("tests/a.py::test_renamed")],                 # does not exist
        [pytest_evidence("tests/a.py::test_a"), Evidence("harness", "OPSEC")],
        [Evidence("telepathy", "anything")],                            # unknown kind
        [],                                                             # claims verification, names nothing
    ],
)
def test_unresolvable_or_missing_evidence_is_a_broken_reference(evidence):
    model = Model((req("REQ-X-001", "a"),), (), (case("VC-1", "a", evidence=evidence),))
    trace = build_trace(model, INDEXES)
    assert status_of(trace, "REQ-X-001") is Status.BROKEN
    assert not trace.ok
    assert any("VC-1" in problem for problem in trace.problems)


def test_a_broken_reference_is_not_excused_by_a_planned_case():
    model = Model(
        (req("REQ-X-001", "a"),),
        (),
        (
            case("VC-1", "a", evidence=[pytest_evidence("tests/a.py::test_gone")]),
            case("VC-2", "a", evidence=[pytest_evidence("tests/later.py::test_x")], planned="M4"),
        ),
    )
    assert status_of(build_trace(model, INDEXES), "REQ-X-001") is Status.BROKEN


def test_relations_to_requirements_that_do_not_exist_are_problems():
    model = Model(
        (req("REQ-X-001", "a"),),
        (Satisfy("ghost", "sentinel.hub"),),
        (case("VC-1", "phantom", evidence=[pytest_evidence("tests/a.py::test_a")]),),
        PARTS,
    )
    trace = build_trace(model, INDEXES)
    assert not trace.ok
    assert any("ghost" in p for p in trace.problems)
    assert any("phantom" in p for p in trace.problems)


def test_a_verification_case_that_verifies_nothing_is_a_problem():
    model = Model((req("REQ-X-001", "a"),), (), (case("VC-9", evidence=[pytest_evidence("tests/a.py::test_a")]),))
    trace = build_trace(model, INDEXES)
    assert not trace.ok
    assert any("VC-9" in p for p in trace.problems)


def test_satisfy_by_a_part_the_model_does_not_declare_is_a_problem():
    model = Model(
        (req("REQ-X-001", "a"),),
        (Satisfy("a", "sentinel.edge.consle"), Satisfy("a", "Arch::sentinel.hub")),
        (),
        frozenset({"sentinel", "edge", "console", "hub"}),
    )
    trace = build_trace(model, INDEXES)
    assert [p for p in trace.problems if "consle" in p]
    assert not [p for p in trace.problems if "hub" in p]      # a package qualifier is not a part


def test_relations_may_name_a_requirement_by_id():
    model = Model(
        (req("REQ-X-001", "a"),),
        (Satisfy("REQ-X-001", "sentinel.hub"),),
        (case("VC-1", "REQ-X-001", evidence=[pytest_evidence("tests/a.py::test_a")]),),
        PARTS,
    )
    trace = build_trace(model, INDEXES)
    row = trace.rows[0]
    assert row.satisfied_by == ("sentinel.hub",)
    assert row.status is Status.VERIFIED


def test_planned_evidence_that_now_exists_is_pointed_out():
    model = Model(
        (req("REQ-X-001", "a"),),
        (),
        (case("VC-1", "a", evidence=[pytest_evidence("tests/b.py::test_b")], planned="M3"),),
    )
    trace = build_trace(model, INDEXES)
    assert status_of(trace, "REQ-X-001") is Status.UNVERIFIED     # still planned until the model says otherwise
    assert trace.rows[0].evidence[0].exists
    assert trace.ok


def test_rows_are_sorted_by_id_and_the_rendering_is_deterministic():
    model = Model(
        (req("REQ-RISK-002", "b"), req("REQ-AI-001", "c"), req("REQ-RISK-001", "a")),
        (Satisfy("b", "z.part"), Satisfy("b", "a.part")),
        (),
        PARTS,
    )
    trace = build_trace(model, INDEXES)
    assert [r.requirement.id for r in trace.rows] == ["REQ-AI-001", "REQ-RISK-001", "REQ-RISK-002"]
    assert trace.rows[2].satisfied_by == ("a.part", "z.part")
    assert render_markdown(trace) == render_markdown(build_trace(model, INDEXES))


def test_rendering_has_a_summary_by_area_and_one_row_per_requirement():
    model = Model(
        (req("REQ-DDIL-001", "a", "Keeps working | denied."), req("REQ-DDIL-002", "b"), req("REQ-SC-001", "c")),
        (Satisfy("a", "sentinel.edge.console"),),
        (
            case("VC-DDIL-001", "a", evidence=[pytest_evidence("tests/a.py::test_a")]),
            case("VC-SC-001", "c", evidence=[pytest_evidence("tests/sbom.py::test_x")], planned="M4"),
        ),
        PARTS,
    )
    text = render_markdown(build_trace(model, INDEXES))
    assert "| DDIL | 2 | 1 | 1 | 0 |" in text
    assert "| SC | 1 | 0 | 1 | 0 |" in text
    assert "| **total** | **3** | **1** | **2** | **0** |" in text
    assert "Keeps working \\| denied." in text        # a pipe in the text cannot break the table
    assert "`sentinel.edge.console`" in text
    assert "`tests/a.py::test_a`" in text
    assert "planned (M4)" in text
    assert "Do not edit by hand" in text


def test_problems_are_rendered_so_the_generated_file_explains_the_failure():
    model = Model((req("REQ-X-001", "a"),), (), (case("VC-1", "a", evidence=[pytest_evidence("tests/gone.py::t")]),))
    text = render_markdown(build_trace(model, INDEXES))
    assert "## Problems" in text
    assert "tests/gone.py::t" in text


def test_markup_in_text_is_escaped_so_the_table_shows_it():
    model = Model((req("REQ-X-001", "a", "Events on node.<id>.> never cross & stay local."),), (), ())
    text = render_markdown(build_trace(model, INDEXES))
    assert "node.&lt;id&gt;.&gt; never cross &amp; stay local." in text


def test_planned_cases_are_listed_with_milestone_reason_and_requirements():
    model = Model(
        (req("REQ-SC-001", "sbom"), req("REQ-SC-002", "signing")),
        (),
        (
            case("VC-SC-002", "signing", evidence=[Evidence("ci", "Sign")], planned="M4", reason="no signature yet"),
            case("VC-SC-001", "sbom", "signing", evidence=[Evidence("ci", "SBOM")], planned="M4", reason="no SBOM"),
        ),
    )
    trace = build_trace(model, INDEXES)
    assert [(p.case, p.milestone, p.requirements) for p in trace.planned] == [
        ("VC-SC-001", "M4", ("REQ-SC-001", "REQ-SC-002")),
        ("VC-SC-002", "M4", ("REQ-SC-002",)),
    ]
    text = render_markdown(trace)
    assert "## Planned evidence" in text
    assert "| VC-SC-001 | M4 | REQ-SC-001<br>REQ-SC-002 | no SBOM |" in text


def test_locators_in_code_spans_are_not_html_escaped():
    model = Model(
        (req("REQ-X-001", "a"),),
        (),
        (case("VC-1", "a", evidence=[Evidence("ci", "Build & sign")], planned="M4", reason="a < b"),),
    )
    text = render_markdown(build_trace(model, INDEXES))
    assert "`Build & sign`" in text
    assert "| a &lt; b |" in text
